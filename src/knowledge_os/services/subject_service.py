"""Subject service: CRUD do agrupador opcional de items dentro de um project."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_os.db.models import Project, Subject
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import session_scope, tiebreak

logger = logging.getLogger(__name__)


class SubjectService:
    """Operações sobre subjects.

    Se `session` não for informada, cada operação abre uma sessão própria
    via get_session(get_engine()).
    """

    def __init__(
        self, session: Session | None = None, connection_id: str | None = None
    ) -> None:
        self._session = session
        self._connection_id = connection_id

    def _find(self, s: Session, project_id: str, name: str) -> Subject | None:
        return s.scalar(
            select(Subject).where(Subject.project_id == project_id, Subject.name == name)
        )

    def create(self, project_id: str, name: str, description: str | None = None) -> Subject:
        """Cria um subject. NotFoundError se project não existe; ValidationError se duplicado."""
        with session_scope(self._session, self._connection_id) as s:
            if s.get(Project, project_id) is None:
                raise NotFoundError(f"Project não encontrado: {project_id}")
            if self._find(s, project_id, name) is not None:
                raise ValidationError(f"Subject já existe no project: {name}")
            sj = Subject(
                id=str(uuid.uuid4()), project_id=project_id, name=name, description=description
            )
            s.add(sj)
            s.commit()
            s.refresh(sj)
            logger.info("Subject criado: %s (project %s)", name, project_id)
            return sj

    def list(self, project_id: str) -> list[Subject]:
        """Lista os subjects de um project ordenados por created_at."""
        with session_scope(self._session, self._connection_id) as s:
            rows = list(
                s.scalars(
                    select(Subject)
                    .where(Subject.project_id == project_id)
                    .order_by(Subject.created_at, *tiebreak(s, "subjects"))
                )
            )
            logger.debug("%d subjects listados", len(rows))
            return rows

    def get(self, project_id: str, name: str) -> Subject:
        """Obtém subject por nome. Levanta NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            sj = self._find(s, project_id, name)
            if sj is None:
                raise NotFoundError(f"Subject não encontrado: {name}")
            return sj

    def delete(self, project_id: str, name: str) -> bool:
        """Remove subject, desvinculando os items (subject_id = None) antes. False se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            sj = self._find(s, project_id, name)
            if sj is None:
                logger.debug("Subject inexistente para delete: %s", name)
                return False
            from sqlalchemy import update

            from knowledge_os.db.models import Item

            s.execute(update(Item).where(Item.subject_id == sj.id).values(subject_id=None))
            s.delete(sj)
            s.commit()
            logger.info("Subject removido: %s", name)
            return True
