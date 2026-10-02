"""Tools MCP de Workspace."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.workspace_schemas import (
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceResponse,
)
from src.services.import_export_service import ImportExportService
from src.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Registra as 6 tools de workspace no servidor."""

    @mcp.tool()
    def workspace_create(name: str, description: str | None = None) -> dict[str, Any]:
        """Cria novo workspace."""
        data = WorkspaceCreate(name=name, description=description)
        ws = WorkspaceService().create(data.name, data.description)
        return WorkspaceResponse.model_validate(ws).model_dump(mode="json")

    @mcp.tool()
    def workspace_list() -> list[dict[str, Any]]:
        """Lista workspaces."""
        rows = WorkspaceService().list()
        return WorkspaceListResponse.model_validate(rows).model_dump(mode="json")

    @mcp.tool()
    def workspace_get(name: str) -> dict[str, Any]:
        """Obtém workspace por nome."""
        ws = WorkspaceService().get(name)
        return WorkspaceResponse.model_validate(ws).model_dump(mode="json")

    @mcp.tool()
    def workspace_delete(name: str) -> dict[str, Any]:
        """Deleta workspace."""
        if WorkspaceService().delete(name):
            return {"status": "deleted", "message": f"Workspace '{name}' removido"}
        return {"status": "not_found", "message": f"Workspace '{name}' não existe"}

    @mcp.tool()
    def workspace_export(name: str) -> dict[str, Any]:
        """Exporta workspace (prepara dados para ZIP)."""
        data = WorkspaceService().export(name)
        return {
            "manifest": data["manifest"],
            "workspace": data["workspace_data"],
            "status": "ok",
        }

    @mcp.tool()
    def workspace_import(file_path: str) -> dict[str, Any]:
        """Importa workspace de ZIP (cria workspace novo; falha se o nome já existe)."""
        ws = ImportExportService().import_workspace(file_path)
        return {"status": "ok", **WorkspaceResponse.model_validate(ws).model_dump(mode="json")}
