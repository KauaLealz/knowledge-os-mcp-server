"""Project service: CRUD e export (import será feito em T5)."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_os.db.models import Project, Workspace
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import (
    EXPORT_VERSION,
    item_to_dict,
    project_to_dict,
    session_scope,
    tiebreak,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class ProjectService:
    """Operações sobre projects.

    Se `session` não for informada, cada operação abre uma sessão própria
    via get_session(get_engine()).
    """

    def __init__(
        self, session: Session | None = None, connection_id: str | None = None
    ) -> None:
        self._session = session
        self._connection_id = connection_id

    def _find(self, s: Session, workspace_id: str, name: str) -> Project | None:
        return s.scalar(
            select(Project).where(Project.workspace_id == workspace_id, Project.name == name)
        )

    def create(self, workspace_id: str, name: str, description: str | None = None) -> Project:
        """Cria um project. NotFoundError se workspace não existe; ValidationError se duplicado."""
        with session_scope(self._session, self._connection_id) as s:
            if s.get(Workspace, workspace_id) is None:
                raise NotFoundError(f"Workspace não encontrado: {workspace_id}")
            if self._find(s, workspace_id, name) is not None:
                raise ValidationError(f"Project já existe no workspace: {name}")
            dm = Project(
                id=str(uuid.uuid4()), workspace_id=workspace_id, name=name, description=description
            )
            s.add(dm)
            s.commit()
            s.refresh(dm)
            logger.info("Project criado: %s (workspace %s)", name, workspace_id)
            return dm

    def list(self, workspace_id: str) -> list[Project]:
        """Lista os projects de um workspace ordenados por created_at."""
        with session_scope(self._session, self._connection_id) as s:
            rows = list(
                s.scalars(
                    select(Project)
                    .where(Project.workspace_id == workspace_id)
                    .order_by(Project.created_at, *tiebreak(s, "projects"))
                )
            )
            logger.debug("%d projects listados", len(rows))
            return rows

    def get(self, workspace_id: str, name: str) -> Project:
        """Obtém project por nome. Levanta NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                raise NotFoundError(f"Project não encontrado: {name}")
            return dm

    def delete(self, workspace_id: str, name: str) -> bool:
        """Remove project (e seus items). False se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                logger.debug("Project inexistente para delete: %s", name)
                return False
            from sqlalchemy import delete, select

            from knowledge_os.db.models import Item, RepoLink
            from knowledge_os.services._common import purge_item_links

            purge_item_links(s, list(s.scalars(select(Item.id).where(Item.project_id == dm.id))))
            s.execute(delete(RepoLink).where(RepoLink.project_id == dm.id))
            s.delete(dm)
            s.commit()
            logger.info("Project removido: %s", name)
            return True

    def export(self, workspace_id: str, name: str) -> dict[str, Any]:
        """Retorna {project_data} com o project e seus items."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                logger.error("Export de project inexistente: %s", name)
                raise NotFoundError(f"Project não encontrado: {name}")
            items = [item_to_dict(i) for i in sorted(dm.items, key=lambda i: i.created_at or 0)]
            logger.info("Project exportado: %s", name)
            return {
                "project_data": {
                    "version": EXPORT_VERSION,
                    "exported_at": utc_now_iso(),
                    "project": project_to_dict(dm),
                    "items": items,
                }
            }
