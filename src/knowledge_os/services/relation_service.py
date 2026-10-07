"""Relation service: operações sobre relações semânticas."""

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knowledge_os.db.models import Item, Relation
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import session_scope

logger = logging.getLogger(__name__)

RELATION_TYPES = (
    "related_to",
    "depends_on",
    "implements",
    "references",
    "supersedes",
    "derived_from",
)


class RelationService:
    """Operações sobre relações entre items.

    Se `session` não for informada, cada operação abre uma sessão própria.
    """

    def __init__(self, session: Session | None = None, connection_id: str | None = None) -> None:
        self._session = session
        self._connection_id = connection_id

    def create(self, source_item_id: str, target_item_id: str, relation_type: str) -> Relation:
        """Cria relação.

        ValidationError para tipo inválido/auto-relação; NotFoundError se item não existe.
        """
        if relation_type not in RELATION_TYPES:
            raise ValidationError(
                f"relation_type inválido: {relation_type}. Válidos: {', '.join(RELATION_TYPES)}"
            )
        if source_item_id == target_item_id:
            raise ValidationError("Um item não pode se relacionar consigo mesmo")
        with session_scope(self._session, self._connection_id) as s:
            for item_id in (source_item_id, target_item_id):
                if s.get(Item, item_id) is None:
                    raise NotFoundError(f"Item não encontrado: {item_id}")
            rel = Relation(
                id=str(uuid.uuid4()),
                source_item_id=source_item_id,
                target_item_id=target_item_id,
                relation_type=relation_type,
            )
            s.add(rel)
            if relation_type == "supersedes":
                # O substituído sai da busca e do pacote de contexto, sem perder o histórico.
                s.get(Item, target_item_id).status = "superseded"
            s.commit()
            s.refresh(rel)
            if self._session is None:
                s.expunge(rel)
            logger.info("Relação criada: %s %s %s", source_item_id, relation_type, target_item_id)
            return rel

    def list_for_workspace(self, workspace_id: str) -> list[Relation]:
        """Lista relações cujos dois items (source e target) pertencem ao workspace."""
        with session_scope(self._session, self._connection_id) as s:
            item_ids = select(Item.id).where(Item.workspace_id == workspace_id)
            rows = list(
                s.scalars(
                    select(Relation)
                    .where(Relation.source_item_id.in_(item_ids))
                    .where(Relation.target_item_id.in_(item_ids))
                    .order_by(Relation.created_at, Relation.id)
                )
            )
            if self._session is None:
                s.expunge_all()
            return rows

    def list_for_items(self, item_ids: list[str]) -> list[Relation]:
        """Lista relações cujos dois items (source e target) estão em `item_ids` — o grafo
        de um escopo qualquer (workspace/project/subject) é só filtrar os items antes."""
        if not item_ids:
            return []
        with session_scope(self._session, self._connection_id) as s:
            rows = list(
                s.scalars(
                    select(Relation)
                    .where(Relation.source_item_id.in_(item_ids))
                    .where(Relation.target_item_id.in_(item_ids))
                    .order_by(Relation.created_at, Relation.id)
                )
            )
            if self._session is None:
                s.expunge_all()
            return rows

    def list(self, item_id: str) -> list[Relation]:
        """Lista relações em que o item é source ou target."""
        with session_scope(self._session, self._connection_id) as s:
            rows = list(
                s.scalars(
                    select(Relation)
                    .where(
                        or_(Relation.source_item_id == item_id, Relation.target_item_id == item_id)
                    )
                    .order_by(Relation.created_at, Relation.id)
                )
            )
            if self._session is None:
                s.expunge_all()
            return rows

    def delete(self, relation_id: str) -> bool:
        """Remove a relação. NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            rel = s.get(Relation, relation_id)
            if rel is None:
                raise NotFoundError(f"Relação não encontrada: {relation_id}")
            s.delete(rel)
            s.commit()
            logger.info("Relação removida: %s", relation_id)
            return True

    def delete_published(self, relation_id: str) -> bool:
        """Remove a relação e, se a connection tem repositório git em modo `direct`,
        republica o item de origem sem essa relação (frontmatter atualizado).

        Simplificação desta rodada: só o modo `direct` republica; em modo `pr` a
        relação só sai do índice (como antes), sem abrir PR — fica para depois.
        """
        from knowledge_os.services.item_service import ItemService

        items = ItemService(connection_id=self._connection_id)
        with session_scope(self._session, self._connection_id) as s:
            rel = s.get(Relation, relation_id)
            if rel is None:
                raise NotFoundError(f"Relação não encontrada: {relation_id}")
            source = s.get(Item, rel.source_item_id)
            s.delete(rel)
            s.flush()
            conn = items._connection_config()  # noqa: SLF001 - mesma connection, sem duplicar
            git = items._git_service(conn) if conn is not None else None  # noqa: SLF001
            if (
                git is not None
                and git.review_mode == "direct"
                and source is not None
                and source.type != "secret"
            ):
                path, content = items._publish_path_and_content(s, source)  # noqa: SLF001
                git.ensure_clone()
                git.publish({path: content}, f"knowledge-os: remove relação de {path}")
            s.commit()
            logger.info("Relação removida: %s", relation_id)
            return True
