"""Tools MCP de Domain. O workspace é identificado pelo nome."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.domain_schemas import DomainCreate, DomainListResponse, DomainResponse
from src.services.domain_service import DomainService
from src.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)


def _workspace_id(workspace: str) -> str:
    """Resolve o nome do workspace para o id (NotFoundError se não existe)."""
    return WorkspaceService().get(workspace).id


def register(mcp: FastMCP) -> None:
    """Registra as 6 tools de domain no servidor."""

    @mcp.tool()
    def domain_create(workspace: str, name: str, description: str | None = None) -> dict[str, Any]:
        """Cria novo domain em um workspace (informado pelo nome)."""
        data = DomainCreate(
            workspace_id=_workspace_id(workspace), name=name, description=description
        )
        dm = DomainService().create(data.workspace_id, data.name, data.description)
        return DomainResponse.model_validate(dm).model_dump(mode="json")

    @mcp.tool()
    def domain_list(workspace: str) -> list[dict[str, Any]]:
        """Lista domains de um workspace."""
        rows = DomainService().list(_workspace_id(workspace))
        return DomainListResponse.model_validate(rows).model_dump(mode="json")

    @mcp.tool()
    def domain_get(workspace: str, name: str) -> dict[str, Any]:
        """Obtém domain por nome."""
        dm = DomainService().get(_workspace_id(workspace), name)
        return DomainResponse.model_validate(dm).model_dump(mode="json")

    @mcp.tool()
    def domain_delete(workspace: str, name: str) -> dict[str, Any]:
        """Deleta domain."""
        if DomainService().delete(_workspace_id(workspace), name):
            return {"status": "deleted", "message": f"Domain '{name}' removido"}
        return {"status": "not_found", "message": f"Domain '{name}' não existe"}

    @mcp.tool()
    def domain_export(workspace: str, name: str) -> dict[str, Any]:
        """Exporta domain (prepara dados para ZIP)."""
        data = DomainService().export(_workspace_id(workspace), name)
        return {"domain": data["domain_data"], "status": "ok"}

    @mcp.tool()
    def domain_import(workspace: str, file_path: str) -> dict[str, Any]:
        """Importa domain de ZIP."""
        # TODO: T5 (import_export_service completo)
        return {"status": "not_implemented"}
