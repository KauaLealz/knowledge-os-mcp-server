"""Item service: CRUD, search, FTS5."""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, bindparam, delete, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.db.dialects import get_dialect
from src.db.models import (
    Artifact,
    Domain,
    Item,
    ItemLabel,
    ItemTag,
    Label,
    Relation,
    Tag,
    Workspace,
)
from src.db.session import connection_id_of, default_connection_id, get_engine, get_session
from src.exceptions import NotFoundError, ValidationError
from src.schemas.item_schemas import ItemCreate, ItemUpdate

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = ("summary", "content", "confidence", "importance", "ttl_days")
_NON_NULLABLE = ("summary", "content")


def _validation_message(exc: PydanticValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
        for e in exc.errors()
    )


class ItemService:
    """Operações de CRUD e busca FTS5 sobre Items.

    Cada chamada abre e fecha a própria sessão. Os objetos retornados ficam
    desanexados, mas com atributos (inclusive tags e labels) já carregados.
    """

    def __init__(self, engine: Engine | None = None, connection_id: str | None = None) -> None:
        """Usa o engine informado ou o da connection (sem ambos, o banco default)."""
        self._engine = engine
        self._connection_id = connection_id

    def _get_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        return get_engine(self._connection_id)

    @property
    def _cid(self) -> str:
        """Connection dona dos workspaces: a informada, a do engine ou a default do JSON."""
        if self._connection_id:
            return self._connection_id
        if self._engine is not None and (known := connection_id_of(self._engine)):
            return known
        return default_connection_id()

    @contextmanager
    def _session(self) -> Iterator[Session]:
        session = get_session(self._get_engine())
        session.expire_on_commit = False
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------ resolução

    def resolve_workspace_id(self, ref: str) -> str:
        """Resolve um workspace por nome ou id. Levanta NotFoundError se não existir."""
        with self._session() as s:
            ws_id = s.scalar(
                select(Workspace.id).where(
                    (Workspace.name == ref) | (Workspace.id == ref),
                    Workspace.connection_id == self._cid,
                )
            )
        if ws_id is None:
            raise NotFoundError(f"Workspace não encontrado: {ref}")
        return ws_id

    def resolve_domain_id(self, workspace_id: str, ref: str) -> str:
        """Resolve um domain (nome ou id) dentro do workspace. Levanta NotFoundError."""
        with self._session() as s:
            dm_id = s.scalar(
                select(Domain.id).where(
                    Domain.workspace_id == workspace_id,
                    (Domain.name == ref) | (Domain.id == ref),
                )
            )
        if dm_id is None:
            raise NotFoundError(f"Domain não encontrado: {ref}")
        return dm_id

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _get_or_create(session: Session, model: type[Tag] | type[Label], names: list[str]) -> list:
        """Reusa registros existentes por nome e cria os que faltam (sem duplicar)."""
        unique = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
        if not unique:
            return []
        found = {r.name: r for r in session.scalars(select(model).where(model.name.in_(unique)))}
        result = []
        for name in unique:
            row = found.get(name)
            if row is None:
                row = model(id=str(uuid.uuid4()), name=name)
                session.add(row)
            result.append(row)
        return result

    @staticmethod
    def _load(session: Session, item_id: str) -> Item:
        item = session.get(Item, item_id)
        if item is None:
            raise NotFoundError(f"Item não encontrado: {item_id}")
        _ = item.tags, item.labels  # carrega antes de desanexar
        return item

    # ------------------------------------------------------------------ CRUD

    def create(
        self,
        workspace_id: str,
        domain_id: str,
        type: str,
        memory_class: str,
        title: str,
        summary: str,
        content: str,
        tags: list[str] | None = None,
        labels: list[str] | None = None,
        confidence: int | None = None,
        importance: int | None = None,
        ttl_days: int | None = None,
    ) -> Item:
        """Cria um item e associa tags e labels (criando as que não existirem)."""
        try:
            data = ItemCreate(
                workspace_id=workspace_id, domain_id=domain_id, type=type,
                memory_class=memory_class, title=title, summary=summary, content=content,
                tags=tags or [], labels=labels or [], confidence=confidence,
                importance=importance, ttl_days=ttl_days,
            )
        except PydanticValidationError as exc:
            raise ValidationError(_validation_message(exc)) from exc

        with self._session() as s:
            if s.get(Workspace, data.workspace_id) is None:
                raise NotFoundError(f"Workspace não encontrado: {data.workspace_id}")
            domain = s.get(Domain, data.domain_id)
            if domain is None or domain.workspace_id != data.workspace_id:
                raise NotFoundError(f"Domain não encontrado: {data.domain_id}")

            item = Item(
                id=str(uuid.uuid4()),
                workspace_id=data.workspace_id,
                domain_id=data.domain_id,
                type=data.type,
                memory_class=data.memory_class,
                title=data.title,
                summary=data.summary,
                content=data.content,
                confidence=data.confidence,
                importance=data.importance,
                ttl_days=data.ttl_days,
                access_count=0,
            )
            item.tags = self._get_or_create(s, Tag, data.tags)
            item.labels = self._get_or_create(s, Label, data.labels)
            s.add(item)
            s.commit()
            logger.info("Item criado: %s", item.id)
            return item

    def update(self, item_id: str, **fields: Any) -> Item:
        """Atualiza summary, content, confidence, importance e/ou ttl_days."""
        unknown = sorted(set(fields) - set(UPDATABLE_FIELDS))
        if unknown:
            raise ValidationError(f"Campos não atualizáveis: {', '.join(unknown)}")
        for name in _NON_NULLABLE:
            if name in fields and fields[name] is None:
                raise ValidationError(f"{name} não pode ser nulo")
        try:
            ItemUpdate(**fields)
        except PydanticValidationError as exc:
            raise ValidationError(_validation_message(exc)) from exc

        with self._session() as s:
            item = self._load(s, item_id)
            if item.memory_class == "ephemeral" and fields.get("ttl_days", item.ttl_days) is None:
                raise ValidationError("ttl_days é obrigatório para memory_class 'ephemeral'")
            for name, value in fields.items():
                setattr(item, name, value)
            s.commit()
            logger.info("Item atualizado: %s", item_id)
            return item

    def delete(self, item_id: str) -> bool:
        """Remove o item e seus vínculos. Levanta NotFoundError se não existir."""
        with self._session() as s:
            item = s.get(Item, item_id)
            if item is None:
                raise NotFoundError(f"Item não encontrado: {item_id}")
            s.execute(delete(ItemTag).where(ItemTag.item_id == item_id))
            s.execute(delete(ItemLabel).where(ItemLabel.item_id == item_id))
            s.execute(
                delete(Relation).where(
                    (Relation.source_item_id == item_id) | (Relation.target_item_id == item_id)
                )
            )
            s.execute(delete(Artifact).where(Artifact.item_id == item_id))
            s.expire(item, ["tags", "labels"])
            s.delete(item)
            s.commit()
            logger.info("Item removido: %s", item_id)
            return True

    def get(self, item_id: str) -> Item:
        """Retorna o item completo (com content, tags e labels)."""
        with self._session() as s:
            return self._load(s, item_id)

    # ------------------------------------------------------------------ busca

    def search(
        self,
        workspace_id: str,
        domain_id: str | None,
        query: str,
        types: list[str] | None = None,
        memory_classes: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Busca FTS5 em title+summary+content. Retorna [{id, title, summary, score}].

        Nunca inclui content. Ordena por importance, confidence, access_count e
        updated_at (desc); o score BM25 desempata. Query vazia lista só por filtros.
        Incrementa access_count e last_accessed dos itens retornados.
        """
        if limit < 1:
            raise ValidationError("limit deve ser >= 1")
        query = (query or "").strip()

        where = ["i.workspace_id = :ws"]
        params: dict[str, Any] = {"ws": workspace_id, "limit": limit}
        expanding: list[str] = []
        if domain_id:
            where.append("i.domain_id = :dm")
            params["dm"] = domain_id
        if types:
            where.append("i.type IN :types")
            params["types"] = list(types)
            expanding.append("types")
        if memory_classes:
            where.append("i.memory_class IN :mclasses")
            params["mclasses"] = list(memory_classes)
            expanding.append("mclasses")

        if query:
            dialect = get_dialect(self._get_engine().dialect.name)
            source, match, score, match_params = dialect.search_parts(query)
            where.insert(0, match)
            params.update(match_params)
        else:
            source = "items i"
            score = "0.0"
        sql = text(
            f"SELECT i.id AS id, i.title AS title, i.summary AS summary, {score} AS score "
            f"FROM {source} WHERE {' AND '.join(where)} "
            "ORDER BY COALESCE(i.importance, 0) DESC, COALESCE(i.confidence, 0) DESC, "
            "COALESCE(i.access_count, 0) DESC, i.updated_at DESC, score DESC LIMIT :limit"
        ).bindparams(*(bindparam(n, expanding=True) for n in expanding))

        with self._session() as s:
            try:
                rows = s.execute(sql, params).mappings().all()
            except OperationalError as exc:
                raise ValidationError(f"Query FTS5 inválida: {query!r} ({exc.orig})") from exc
            results = [
                {"id": r["id"], "title": r["title"], "summary": r["summary"],
                 "score": float(r["score"])}
                for r in rows
            ]
            if results:
                s.execute(
                    update(Item)
                    .where(Item.id.in_([r["id"] for r in results]))
                    .values(
                        access_count=func.coalesce(Item.access_count, 0) + 1,
                        last_accessed=datetime.utcnow(),
                        updated_at=Item.updated_at,  # busca não conta como edição
                    )
                    .execution_options(synchronize_session=False)
                )
                s.commit()
            return results
