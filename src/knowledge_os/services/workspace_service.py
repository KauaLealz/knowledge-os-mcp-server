"""Workspace service: CRUD e export (import será feito em T5)."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_os.db.models import Workspace
from knowledge_os.db.session import default_connection_id
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import (
    EXPORT_VERSION,
    domain_to_dict,
    item_to_dict,
    session_scope,
    tiebreak,
    utc_now_iso,
    workspace_to_dict,
)

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Operações sobre workspaces.

    Se `session` não for informada, cada operação abre uma sessão própria no banco da
    connection (get_engine(connection_id)). Todas as operações ficam restritas à
    connection; sem connection_id vale a default do connections.json.
    """

    def __init__(
        self, session: Session | None = None, connection_id: str | None = None
    ) -> None:
        self._session = session
        self._connection_id = connection_id

    @property
    def _cid(self) -> str:
        return self._connection_id or default_connection_id()

    def _find(self, s: Session, name: str) -> Workspace | None:
        return s.scalar(
            select(Workspace).where(
                Workspace.name == name, Workspace.connection_id == self._cid
            )
        )

    def create(self, name: str, description: str | None = None) -> Workspace:
        """Cria um workspace. Levanta ValidationError se o nome já existe."""
        with session_scope(self._session, self._connection_id) as s:
            if self._find(s, name) is not None:
                raise ValidationError(f"Workspace já existe: {name}")
            ws = Workspace(
                id=str(uuid.uuid4()),
                connection_id=self._cid,
                name=name,
                description=description,
            )
            s.add(ws)
            s.commit()
            s.refresh(ws)
            logger.info("Workspace criado: %s", name)
            return ws

    def list(self) -> list[Workspace]:
        """Lista todos os workspaces ordenados por created_at."""
        with session_scope(self._session, self._connection_id) as s:
            stmt = (
                select(Workspace)
                .where(Workspace.connection_id == self._cid)
                .order_by(Workspace.created_at, *tiebreak(s, "workspaces"))
            )
            rows = list(s.scalars(stmt))
            logger.debug("%d workspaces listados", len(rows))
            return rows

    def get(self, name: str) -> Workspace:
        """Obtém workspace por nome. Levanta NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            ws = self._find(s, name)
            if ws is None:
                raise NotFoundError(f"Workspace não encontrado: {name}")
            return ws

    def delete(self, name: str) -> bool:
        """Remove workspace (e seus domains/items). False se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            ws = self._find(s, name)
            if ws is None:
                logger.debug("Workspace inexistente para delete: %s", name)
                return False
            from sqlalchemy import delete, select

            from knowledge_os.db.models import Item, RepoLink
            from knowledge_os.services._common import purge_item_links

            purge_item_links(s, list(s.scalars(select(Item.id).where(Item.workspace_id == ws.id))))
            s.execute(delete(RepoLink).where(RepoLink.workspace_id == ws.id))
            s.delete(ws)
            s.commit()
            logger.info("Workspace removido: %s", name)
            return True

    def export(self, name: str) -> dict[str, Any]:
        """Retorna {manifest, workspace_data} pronto para empacotar em ZIP."""
        with session_scope(self._session, self._connection_id) as s:
            ws = self._find(s, name)
            if ws is None:
                logger.error("Export de workspace inexistente: %s", name)
                raise NotFoundError(f"Workspace não encontrado: {name}")
            domains = [domain_to_dict(d) for d in sorted(ws.domains, key=lambda d: d.name)]
            items = [item_to_dict(i) for i in sorted(ws.items, key=lambda i: i.created_at or 0)]
            logger.info("Workspace exportado: %s", name)
            return {
                "manifest": {
                    "version": EXPORT_VERSION,
                    "type": "workspace",
                    "name": ws.name,
                    "exported_at": utc_now_iso(),
                    "counts": {"domains": len(domains), "items": len(items)},
                },
                "workspace_data": {
                    "workspace": workspace_to_dict(ws),
                    "domains": domains,
                    "items": items,
                },
            }
