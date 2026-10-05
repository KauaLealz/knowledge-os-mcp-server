"""Tag service: gerenciar tags únicas."""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from knowledge_os.db.models import ItemTag, Tag
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import session_scope

logger = logging.getLogger(__name__)


class TagService:
    """Operações sobre tags.

    Se `session` não for informada, cada operação abre uma sessão própria.
    """

    def __init__(
        self, session: Session | None = None, connection_id: str | None = None
    ) -> None:
        self._session = session
        self._connection_id = connection_id

    def create(self, name: str) -> Tag:
        """Cria tag única. ValidationError se vazia ou duplicada."""
        name = name.strip()
        if not name or len(name) > 100:
            raise ValidationError("Nome deve ter entre 1 e 100 caracteres")
        with session_scope(self._session, self._connection_id) as s:
            if s.scalar(select(Tag).where(Tag.name == name)) is not None:
                raise ValidationError(f"Tag já existe: {name}")
            obj = Tag(id=str(uuid.uuid4()), name=name)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            if self._session is None:
                s.expunge(obj)
            logger.info("Tag criada: %s", name)
            return obj

    def list(self) -> list[Tag]:
        """Lista todas as tags por nome."""
        with session_scope(self._session, self._connection_id) as s:
            rows = list(s.scalars(select(Tag).order_by(Tag.name)))
            if self._session is None:
                s.expunge_all()
            return rows

    def delete(self, tag_id: str) -> bool:
        """Remove a tag e seus vínculos com items. NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            obj = s.get(Tag, tag_id)
            if obj is None:
                raise NotFoundError(f"Tag não encontrada: {tag_id}")
            s.execute(delete(ItemTag).where(ItemTag.tag_id == tag_id))
            s.delete(obj)
            s.commit()
            s.expire_all()
            logger.info("Tag removida: %s", tag_id)
            return True
