"""Item service: CRUD, upsert por chave, lote, busca FTS5."""

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
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
from src.db.search_query import match_expressions
from src.db.session import (
    connection_id_of,
    default_connection_id,
    get_engine,
    get_session,
    run_with_retry,
)
from src.exceptions import NotFoundError, ValidationError
from src.schemas.item_schemas import MEMORY_CLASSES, ItemCreate, ItemUpdate
from src.services.secret_guard import ensure_no_secrets

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = (
    "title", "type", "summary", "content", "confidence", "importance", "ttl_days",
    "keywords", "source", "status", "scope_paths", "tags", "labels",
)
_NON_NULLABLE = ("title", "type", "summary", "content")
_TEXT_FIELDS = ("title", "summary", "content", "keywords")
_RANK = {m: i for i, m in enumerate(MEMORY_CLASSES)}


def _validation_message(exc: PydanticValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
        for e in exc.errors()
    )


def _expiry(
    memory_class: str, ttl_days: int | None, base: datetime | None = None
) -> datetime | None:
    """Data de expiração de um ephemeral (None para as demais classes)."""
    if memory_class != "ephemeral" or not ttl_days:
        return None
    return (base or datetime.utcnow()) + timedelta(days=ttl_days)


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

    def ensure_location(self, workspace: str, domain: str) -> tuple[str, str]:
        """Resolve workspace e domain por nome ou id, criando os que não existem."""
        return run_with_retry(
            lambda: self._ensure_location_once(workspace, domain), retry_conflict=True
        )

    def _ensure_location_once(self, workspace: str, domain: str) -> tuple[str, str]:
        with self._session() as s:
            ws = s.scalar(
                select(Workspace).where(
                    (Workspace.name == workspace) | (Workspace.id == workspace),
                    Workspace.connection_id == self._cid,
                )
            )
            if ws is None:
                ws = Workspace(id=str(uuid.uuid4()), name=workspace, connection_id=self._cid)
                s.add(ws)
                s.flush()
            dm = s.scalar(
                select(Domain).where(
                    Domain.workspace_id == ws.id, (Domain.name == domain) | (Domain.id == domain)
                )
            )
            if dm is None:
                dm = Domain(id=str(uuid.uuid4()), workspace_id=ws.id, name=domain)
                s.add(dm)
            s.commit()
            return ws.id, dm.id

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

    @staticmethod
    def _validate_create(**kwargs: Any) -> ItemCreate:
        try:
            data = ItemCreate(**kwargs)
        except PydanticValidationError as exc:
            raise ValidationError(_validation_message(exc)) from exc
        ensure_no_secrets(**{f: getattr(data, f) for f in _TEXT_FIELDS})
        return data

    def _insert(self, s: Session, data: ItemCreate) -> Item:
        if s.get(Workspace, data.workspace_id) is None:
            raise NotFoundError(f"Workspace não encontrado: {data.workspace_id}")
        domain = s.get(Domain, data.domain_id)
        if domain is None or domain.workspace_id != data.workspace_id:
            raise NotFoundError(f"Domain não encontrado: {data.domain_id}")
        if data.key and self._by_key(s, data.domain_id, data.key) is not None:
            raise ValidationError(f"Já existe item com key {data.key!r} neste domain (use upsert)")
        now = datetime.utcnow()
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
            expires_at=_expiry(data.memory_class, data.ttl_days, now),
            key=data.key,
            keywords=data.keywords,
            source=data.source,
            status=data.status,
            scope_paths=json.dumps(data.scope_paths) if data.scope_paths else None,
            access_count=0,
            created_at=now,
            updated_at=now,
        )
        item.tags = self._get_or_create(s, Tag, data.tags)
        item.labels = self._get_or_create(s, Label, data.labels)
        s.add(item)
        return item

    @staticmethod
    def _check_update(fields: dict[str, Any]) -> None:
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
        ensure_no_secrets(**{f: fields.get(f) for f in _TEXT_FIELDS})

    def _apply(self, s: Session, item: Item, fields: dict[str, Any]) -> bool:
        """Aplica campos ao item na sessão. True se algo mudou."""
        changed = False
        if item.memory_class == "ephemeral" and fields.get("ttl_days", item.ttl_days) is None:
            raise ValidationError("ttl_days é obrigatório para memory_class 'ephemeral'")
        for name, value in fields.items():
            if name == "tags":
                if sorted(t.name for t in item.tags) != sorted(set(value)):
                    item.tags = self._get_or_create(s, Tag, value)
                    changed = True
            elif name == "labels":
                if sorted(lb.name for lb in item.labels) != sorted(set(value)):
                    item.labels = self._get_or_create(s, Label, value)
                    changed = True
            elif name == "scope_paths":
                encoded = json.dumps(value) if value else None
                if item.scope_paths != encoded:
                    item.scope_paths = encoded
                    changed = True
            elif getattr(item, name) != value:
                setattr(item, name, value)
                changed = True
        if "ttl_days" in fields and item.memory_class == "ephemeral":
            item.expires_at = _expiry(item.memory_class, item.ttl_days)
        return changed

    @staticmethod
    def _raise_class(item: Item, target: str) -> bool:
        """Sobe a classe de memória se `target` for maior; nunca rebaixa. True se subiu."""
        if target not in _RANK:
            raise ValidationError(f"memory_class inválido: {target!r}")
        if _RANK[target] <= _RANK.get(item.memory_class, 0):
            return False
        item.memory_class = target
        if target != "ephemeral":
            item.ttl_days = None
            item.expires_at = None
        return True

    @staticmethod
    def _by_key(s: Session, domain_id: str, key: str) -> Item | None:
        return s.scalar(select(Item).where(Item.domain_id == domain_id, Item.key == key))

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
        key: str | None = None,
        keywords: str | None = None,
        source: str | None = None,
        status: str = "active",
        scope_paths: list[str] | None = None,
    ) -> Item:
        """Cria um item e associa tags e labels (criando as que não existirem)."""
        data = self._validate_create(
            workspace_id=workspace_id, domain_id=domain_id, type=type,
            memory_class=memory_class, title=title, summary=summary, content=content,
            tags=tags or [], labels=labels or [], confidence=confidence,
            importance=importance, ttl_days=ttl_days, key=key, keywords=keywords,
            source=source, status=status, scope_paths=scope_paths or [],
        )
        with self._session() as s:
            item = self._insert(s, data)
            s.commit()
            logger.info("Item criado: %s", item.id)
            return self._load(s, item.id)

    def update(self, item_id: str, **fields: Any) -> Item:
        """Atualiza só os campos informados (tags e labels substituem as atuais)."""
        self._check_update(fields)
        with self._session() as s:
            item = self._load(s, item_id)
            self._apply(s, item, fields)
            s.commit()
            logger.info("Item atualizado: %s", item_id)
            return self._load(s, item_id)

    def upsert(
        self, workspace_id: str, domain_id: str, key: str, **fields: Any
    ) -> tuple[Item, str]:
        """Cria ou atualiza o item de `key` no domain. Retorna (item, created|updated|unchanged).

        `memory_class` só sobe (nunca rebaixa um item existente). Na criação, os campos
        obrigatórios de item_create valem.
        """
        with self._session() as s:
            item, action = self._upsert_in(s, workspace_id, domain_id, key, fields)
            s.commit()
            return self._load(s, item.id), action

    def _upsert_in(
        self, s: Session, workspace_id: str, domain_id: str, key: str, fields: dict[str, Any]
    ) -> tuple[Item, str]:
        fields = {k: v for k, v in fields.items() if v is not None}
        existing = self._by_key(s, domain_id, key)
        if existing is None:
            data = self._validate_create(
                workspace_id=workspace_id, domain_id=domain_id, key=key,
                **{"tags": [], "labels": [], "scope_paths": [], **fields},
            )
            return self._insert(s, data), "created"
        memory_class = fields.pop("memory_class", None)
        self._check_update(fields)
        _ = existing.tags, existing.labels
        changed = self._apply(s, existing, fields)
        if memory_class:
            changed = self._raise_class(existing, memory_class) or changed
        return existing, ("updated" if changed else "unchanged")

    def batch_upsert(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Upsert de vários itens numa transação. Cada entrada traz workspace, domain e key."""
        for i, e in enumerate(entries):
            missing = [f for f in ("workspace", "domain", "key") if not e.get(f)]
            if missing:
                raise ValidationError(f"Entrada {i}: faltam {', '.join(missing)}")
        return [
            {k: r[k] for k in ("key", "id", "action")} for r in self.save(entries)
        ]

    def save(
        self, entries: list[dict[str, Any]], default_location: tuple[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Grava vários itens numa transação; cada entrada escolhe o modo pelo que traz.

        - `id`: atualiza esse item (só os campos informados).
        - `key`: upsert no domain (cria ou atualiza; não duplica).
        - nenhum dos dois: cria e devolve `similar` com títulos parecidos já existentes.

        Em qualquer modo: `memory_class` só sobe (promoção), `ttl_days` renova um ephemeral a
        partir de agora, e `relations: [{type, target}]` liga ao alvo (id, ou key do mesmo
        domain, inclusive itens criados no mesmo lote); `supersedes` marca o alvo como
        substituído. Workspace/domain vêm da entrada ou de `default_location` e são criados se
        não existirem. Qualquer erro desfaz o lote inteiro e aponta a entrada.
        """
        if not entries:
            return []
        plans = []
        for i, raw in enumerate(entries):
            e = dict(raw)
            relations = e.pop("relations", None) or []
            item_id, key = e.pop("id", None), e.pop("key", None)
            ws, dm = e.pop("workspace", None), e.pop("domain", None)
            location = None
            if not item_id:
                if ws and dm:
                    location = self.ensure_location(ws, dm)
                elif default_location:
                    location = default_location
                else:
                    raise ValidationError(f"Entrada {i}: informe workspace e domain (ou project)")
            fields = {k: v for k, v in e.items() if v is not None}
            plans.append((i, item_id, key, location, fields, relations))

        return run_with_retry(lambda: self._save_plans(plans))

    def _save_plans(self, plans: list[tuple]) -> list[dict[str, Any]]:
        """Executa o plano numa transação (reexecutável: cada tentativa copia os campos)."""
        results: list[dict[str, Any]] = []
        links: list[tuple[int, Item, dict[str, Any]]] = []
        with self._session() as s:
            for i, item_id, key, location, fields, relations in plans:
                fields = dict(fields)  # o ramo de id consome `memory_class` com pop
                label = key or item_id or fields.get("title", "?")
                similar: list[dict[str, Any]] = []
                try:
                    if item_id:
                        item = self._load(s, item_id)
                        memory_class = fields.pop("memory_class", None)
                        self._check_update(fields)
                        changed = self._apply(s, item, fields)
                        if memory_class:
                            changed = self._raise_class(item, memory_class) or changed
                        action = "updated" if changed else "unchanged"
                    elif key:
                        item, action = self._upsert_in(s, location[0], location[1], key, fields)
                    else:
                        if fields.get("title"):
                            similar = self.similar(location[0], fields["title"])
                        data = self._validate_create(
                            workspace_id=location[0], domain_id=location[1],
                            **{"tags": [], "labels": [], "scope_paths": [], **fields},
                        )
                        item, action = self._insert(s, data), "created"
                    s.flush()
                except (ValidationError, NotFoundError) as exc:
                    raise ValidationError(f"Entrada {i} ({label}): {exc}") from exc
                row: dict[str, Any] = {"index": i, "id": item.id, "key": item.key, "action": action}
                if similar:
                    row["similar"] = similar
                results.append(row)
                links += [(i, item, r) for r in relations]
            for i, item, rel in links:
                try:
                    created = self._relate(s, item, rel)
                except (ValidationError, NotFoundError) as exc:
                    raise ValidationError(f"Entrada {i}, relação {rel}: {exc}") from exc
                if created:
                    results[i]["relations"] = results[i].get("relations", 0) + 1
            s.commit()
        return results

    def _relate(self, s: Session, item: Item, rel: dict[str, Any]) -> bool:
        """Cria a relação item → alvo (id ou key do mesmo domain). False se já existia."""
        from src.services.relation_service import RELATION_TYPES

        rtype, target_ref = rel.get("type"), rel.get("target")
        if rtype not in RELATION_TYPES:
            raise ValidationError(f"type inválido: {rtype!r}. Válidos: {', '.join(RELATION_TYPES)}")
        if not target_ref:
            raise ValidationError("relação sem target")
        target = s.get(Item, target_ref) or self._by_key(s, item.domain_id, target_ref)
        if target is None:
            raise NotFoundError(f"Alvo não encontrado: {target_ref}")
        if target.id == item.id:
            raise ValidationError("Um item não pode se relacionar consigo mesmo")
        exists = s.scalar(
            select(Relation.id).where(
                Relation.source_item_id == item.id,
                Relation.target_item_id == target.id,
                Relation.relation_type == rtype,
            )
        )
        if exists:
            return False
        s.add(Relation(id=str(uuid.uuid4()), source_item_id=item.id,
                       target_item_id=target.id, relation_type=rtype))
        if rtype == "supersedes":
            target.status = "superseded"
        return True

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

    def get_by_key(self, domain_id: str, key: str) -> Item:
        """Item de `key` no domain. Levanta NotFoundError."""
        with self._session() as s:
            item = self._by_key(s, domain_id, key)
            if item is None:
                raise NotFoundError(f"Item não encontrado: key {key!r}")
            return self._load(s, item.id)

    # ------------------------------------------------------------------ busca

    def search(
        self,
        workspace_id: str | None,
        domain_id: str | None,
        query: str,
        types: list[str] | None = None,
        memory_classes: list[str] | None = None,
        limit: int = 10,
        include_inactive: bool = False,
        track: bool = True,
    ) -> list[dict[str, Any]]:
        """Busca FTS5 em title+summary+keywords+content. Nunca inclui content.

        Com consulta, ordena por relevância (BM25 com peso maior para o título) e desempata
        por importance, confidence, access_count e updated_at. Sem consulta, lista por esses
        critérios. Sem workspace, busca em todos os da connection. Omite itens substituídos,
        obsoletos e ephemeral vencidos, salvo `include_inactive`. Em SQLite, a consulta é
        normalizada para PT-BR (sem acento, radical, prefixo); se exigir todos os termos não
        acha nada, tenta qualquer termo. Com `track`, incrementa access_count dos retornados.
        """
        if limit < 1:
            raise ValidationError("limit deve ser >= 1")
        query = (query or "").strip()
        engine = self._get_engine()
        dialect_name = engine.dialect.name

        where: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        expanding: list[str] = []
        if workspace_id:
            where.append("i.workspace_id = :ws")
            params["ws"] = workspace_id
        else:
            where.append(
                "i.workspace_id IN (SELECT w.id FROM workspaces w WHERE w.connection_id = :cid)"
            )
            params["cid"] = self._cid
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
        if not include_inactive:
            where.append("COALESCE(i.status, 'active') IN ('active', 'done')")
            where.append("(i.expires_at IS NULL OR i.expires_at > :now)")
            params["now"] = datetime.utcnow()

        tie = (
            "COALESCE(i.importance, 0) DESC, COALESCE(i.confidence, 0) DESC, "
            "COALESCE(i.access_count, 0) DESC, i.updated_at DESC"
        )
        columns = (
            "i.id AS id, i.item_key AS item_key, i.type AS type, i.memory_class AS memory_class, "
            "d.name AS domain, i.title AS title, i.summary AS summary, "
            "COALESCE(i.access_count, 0) AS uses"
        )
        if not query:
            attempts = [("items i JOIN domains d ON d.id = i.domain_id", None, "0.0", {})]
            order = tie
        else:
            dialect = get_dialect(dialect_name)
            raw = match_expressions(query) if dialect_name == "sqlite" else [query]
            if not raw:
                return []
            attempts = []
            for expression in raw:
                source, match, score, mparams = dialect.search_parts(expression)
                joined = f"{source} JOIN domains d ON d.id = i.domain_id"
                attempts.append((joined, match, score, mparams))
            order = f"score DESC, {tie}"

        with self._session() as s:
            rows: list[Any] = []
            for source, match, score, mparams in attempts:
                clauses = ([match] if match else []) + where
                sql = text(
                    f"SELECT {columns}, {score} AS score FROM {source} "
                    f"WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT :limit"
                ).bindparams(*(bindparam(n, expanding=True) for n in expanding))
                try:
                    rows = s.execute(sql, {**params, **mparams}).mappings().all()
                except OperationalError as exc:
                    raise ValidationError(f"Query FTS5 inválida: {query!r} ({exc.orig})") from exc
                if rows:
                    break
            results = [
                {
                    "id": r["id"], "key": r["item_key"], "type": r["type"],
                    "memory_class": r["memory_class"], "domain": r["domain"],
                    "title": r["title"], "summary": r["summary"], "score": float(r["score"]),
                    "uses": int(r["uses"] or 0),
                }
                for r in rows
            ]
            if results and track:
                ids = [r["id"] for r in results]
                run_with_retry(lambda: self._count_use(ids))
            return results

    def _count_use(self, ids: list[str]) -> None:
        with self._session() as s:
            s.execute(
                update(Item)
                .where(Item.id.in_(ids))
                .values(
                    access_count=func.coalesce(Item.access_count, 0) + 1,
                    last_accessed=datetime.utcnow(),
                    updated_at=Item.updated_at,  # busca não conta como edição
                )
                .execution_options(synchronize_session=False)
            )
            s.commit()

    def similar(self, workspace_id: str, title: str, limit: int = 3) -> list[dict[str, Any]]:
        """Itens ativos do workspace com título parecido (para avisar antes de duplicar)."""
        found = self.search(workspace_id, None, title, limit=limit, track=False)
        return [{k: r[k] for k in ("id", "key", "title", "summary")} for r in found]
