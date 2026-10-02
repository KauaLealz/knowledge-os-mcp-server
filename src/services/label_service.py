"""Label service: gerenciar labels únicas."""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db.models import ItemLabel, Label
from src.exceptions import NotFoundError, ValidationError
from src.services._common import session_scope

logger = logging.getLogger(__name__)


class LabelService:
    """Operações sobre labels.

    Se `session` não for informada, cada operação abre uma sessão própria.
    """

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def create(self, name: str) -> Label:
        """Cria label única. ValidationError se vazia ou duplicada."""
        name = name.strip()
        if not name or len(name) > 100:
            raise ValidationError("Nome deve ter entre 1 e 100 caracteres")
        with session_scope(self._session) as s:
            if s.scalar(select(Label).where(Label.name == name)) is not None:
                raise ValidationError(f"Label já existe: {name}")
            obj = Label(id=str(uuid.uuid4()), name=name)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            if self._session is None:
                s.expunge(obj)
            logger.info("Label criada: %s", name)
            return obj

    def list(self) -> list[Label]:
        """Lista todas as labels por nome."""
        with session_scope(self._session) as s:
            rows = list(s.scalars(select(Label).order_by(Label.name)))
            if self._session is None:
                s.expunge_all()
            return rows

    def delete(self, label_id: str) -> bool:
        """Remove a label e seus vínculos com items. NotFoundError se não existe."""
        with session_scope(self._session) as s:
            obj = s.get(Label, label_id)
            if obj is None:
                raise NotFoundError(f"Label não encontrada: {label_id}")
            s.execute(delete(ItemLabel).where(ItemLabel.label_id == label_id))
            s.delete(obj)
            s.commit()
            s.expire_all()
            logger.info("Label removida: %s", label_id)
            return True
