"""Relation service: operações sobre relações semânticas."""

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.db.models import Item, Relation
from src.exceptions import NotFoundError, ValidationError
from src.services._common import session_scope

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

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def create(self, source_item_id: str, target_item_id: str, relation_type: str) -> Relation:
        """Cria relação. ValidationError para tipo inválido/auto-relação; NotFoundError se item não existe."""
        if relation_type not in RELATION_TYPES:
            raise ValidationError(
                f"relation_type inválido: {relation_type}. Válidos: {', '.join(RELATION_TYPES)}"
            )
        if source_item_id == target_item_id:
            raise ValidationError("Um item não pode se relacionar consigo mesmo")
        with session_scope(self._session) as s:
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
            s.commit()
            s.refresh(rel)
            if self._session is None:
                s.expunge(rel)
            logger.info("Relação criada: %s %s %s", source_item_id, relation_type, target_item_id)
            return rel

    def list(self, item_id: str) -> list[Relation]:
        """Lista relações em que o item é source ou target."""
        with session_scope(self._session) as s:
            rows = list(
                s.scalars(
                    select(Relation)
                    .where(or_(Relation.source_item_id == item_id, Relation.target_item_id == item_id))
                    .order_by(Relation.created_at, Relation.id)
                )
            )
            if self._session is None:
                s.expunge_all()
            return rows

    def delete(self, relation_id: str) -> bool:
        """Remove a relação. NotFoundError se não existe."""
        with session_scope(self._session) as s:
            rel = s.get(Relation, relation_id)
            if rel is None:
                raise NotFoundError(f"Relação não encontrada: {relation_id}")
            s.delete(rel)
            s.commit()
            logger.info("Relação removida: %s", relation_id)
            return True
