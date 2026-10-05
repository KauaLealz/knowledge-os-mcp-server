"""Domain service: CRUD e export (import será feito em T5)."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Domain, Workspace
from src.exceptions import NotFoundError, ValidationError
from src.services._common import (
    EXPORT_VERSION,
    domain_to_dict,
    item_to_dict,
    session_scope,
    tiebreak,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class DomainService:
    """Operações sobre domains.

    Se `session` não for informada, cada operação abre uma sessão própria
    via get_session(get_engine()).
    """

    def __init__(
        self, session: Session | None = None, connection_id: str | None = None
    ) -> None:
        self._session = session
        self._connection_id = connection_id

    def _find(self, s: Session, workspace_id: str, name: str) -> Domain | None:
        return s.scalar(
            select(Domain).where(Domain.workspace_id == workspace_id, Domain.name == name)
        )

    def create(self, workspace_id: str, name: str, description: str | None = None) -> Domain:
        """Cria um domain. NotFoundError se o workspace não existe; ValidationError se duplicado."""
        with session_scope(self._session, self._connection_id) as s:
            if s.get(Workspace, workspace_id) is None:
                raise NotFoundError(f"Workspace não encontrado: {workspace_id}")
            if self._find(s, workspace_id, name) is not None:
                raise ValidationError(f"Domain já existe no workspace: {name}")
            dm = Domain(
                id=str(uuid.uuid4()), workspace_id=workspace_id, name=name, description=description
            )
            s.add(dm)
            s.commit()
            s.refresh(dm)
            logger.info("Domain criado: %s (workspace %s)", name, workspace_id)
            return dm

    def list(self, workspace_id: str) -> list[Domain]:
        """Lista os domains de um workspace ordenados por created_at."""
        with session_scope(self._session, self._connection_id) as s:
            rows = list(
                s.scalars(
                    select(Domain)
                    .where(Domain.workspace_id == workspace_id)
                    .order_by(Domain.created_at, *tiebreak(s, "domains"))
                )
            )
            logger.debug("%d domains listados", len(rows))
            return rows

    def get(self, workspace_id: str, name: str) -> Domain:
        """Obtém domain por nome. Levanta NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                raise NotFoundError(f"Domain não encontrado: {name}")
            return dm

    def delete(self, workspace_id: str, name: str) -> bool:
        """Remove domain (e seus items). False se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                logger.debug("Domain inexistente para delete: %s", name)
                return False
            from sqlalchemy import delete, select

            from src.db.models import Item, ProjectLink
            from src.services._common import purge_item_links

            purge_item_links(s, list(s.scalars(select(Item.id).where(Item.domain_id == dm.id))))
            s.execute(delete(ProjectLink).where(ProjectLink.domain_id == dm.id))
            s.delete(dm)
            s.commit()
            logger.info("Domain removido: %s", name)
            return True

    def export(self, workspace_id: str, name: str) -> dict[str, Any]:
        """Retorna {domain_data} com o domain e seus items."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                logger.error("Export de domain inexistente: %s", name)
                raise NotFoundError(f"Domain não encontrado: {name}")
            items = [item_to_dict(i) for i in sorted(dm.items, key=lambda i: i.created_at or 0)]
            logger.info("Domain exportado: %s", name)
            return {
                "domain_data": {
                    "version": EXPORT_VERSION,
                    "exported_at": utc_now_iso(),
                    "domain": domain_to_dict(dm),
                    "items": items,
                }
            }
