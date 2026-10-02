"""Tools MCP de Workspace."""

import logging
from datetime import datetime
from typing import Any

from fastmcp import FastMCP

from src.config import EXPORTS_DIR
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
    def workspace_create(
        name: str, description: str | None = None, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Cria um workspace (contexto grande de conhecimento: projeto, assunto, pessoa).

        **Use quando:** Começar um novo projeto/assunto ou separar conhecimento em silos.
        **Retorna:** {id, name, description, created_at}.
        **Exemplo:** workspace_create(name="Python Learning", description="Tudo sobre Python 3.12")
        **Notas:** Nome único. description é opcional (Markdown). connection_id: opcional; sem ele
            usa a connection default (sqlite_local).
        """
        data = WorkspaceCreate(name=name, description=description)
        ws = WorkspaceService(connection_id=connection_id).create(data.name, data.description)
        return WorkspaceResponse.model_validate(ws).model_dump(mode="json")

    @mcp.tool()
    def workspace_list(connection_id: str | None = None) -> list[dict[str, Any]]:
        """Lista os workspaces de uma connection.

        **Use quando:** Descobrir os nomes de workspace antes de criar domains ou buscar items.
        **Retorna:** Lista de workspaces (id, name, description, ...). Vazia em banco novo.
        **Exemplo:** workspace_list(connection_id="postgres_prod")
        **Notas:** connection_id: opcional; sem ele usa a connection default (sqlite_local).
        """
        rows = WorkspaceService(connection_id=connection_id).list()
        return WorkspaceListResponse.model_validate(rows).model_dump(mode="json")

    @mcp.tool()
    def workspace_get(name: str, connection_id: str | None = None) -> dict[str, Any]:
        """Obtém um workspace pelo nome.

        **Use quando:** Confirmar que um workspace existe ou ler sua descrição.
        **Retorna:** Dados do workspace.
        **Exemplo:** workspace_get(name="Python Learning")
        **Notas:** Erro de not found se o nome não existir. connection_id: opcional; sem ele usa a
            connection default (sqlite_local).
        """
        ws = WorkspaceService(connection_id=connection_id).get(name)
        return WorkspaceResponse.model_validate(ws).model_dump(mode="json")

    @mcp.tool()
    def workspace_delete(name: str, connection_id: str | None = None) -> dict[str, Any]:
        """Deleta um workspace pelo nome.

        **Use quando:** Descartar um contexto inteiro que não é mais necessário.
        **Retorna:** {status: deleted|not_found, message}.
        **Exemplo:** workspace_delete(name="Rascunhos")
        **Notas:** Destrutivo: leva domains e items junto. Faça workspace_export antes se houver
            dúvida. connection_id: opcional; sem ele usa a connection default (sqlite_local).
        """
        if WorkspaceService(connection_id=connection_id).delete(name):
            return {"status": "deleted", "message": f"Workspace '{name}' removido"}
        return {"status": "not_found", "message": f"Workspace '{name}' não existe"}

    @mcp.tool()
    def workspace_export(name: str, connection_id: str | None = None) -> dict[str, Any]:
        """Exporta um workspace (manifest + dados) para backup ou compartilhamento.

        **Use quando:** Backup antes de mudanças grandes ou para levar um workspace a outra
            connection.
        **Retorna:** {status: ok, file_path, size_mb, manifest, workspace}.
        **Exemplo:** workspace_export(name="Python Learning")
        **Notas:** Grava o ZIP em exports/ (file_path) e devolve os dados; o restore é feito por
            workspace_import a partir de um ZIP. connection_id: opcional; sem ele usa a connection
            default (sqlite_local).
        """
        data = WorkspaceService(connection_id=connection_id).export(name)
        ws_id = WorkspaceService(connection_id=connection_id).get(name).id
        zip_bytes = ImportExportService(connection_id=connection_id).export_workspace(ws_id)
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        zip_path = EXPORTS_DIR / f"workspace_{ws_id}_{stamp}.zip"
        zip_path.write_bytes(zip_bytes)
        return {
            "manifest": data["manifest"],
            "workspace": data["workspace_data"],
            "file_path": str(zip_path),
            "size_mb": round(len(zip_bytes) / (1024 * 1024), 2),
            "status": "ok",
        }

    @mcp.tool()
    def workspace_import(file_path: str, connection_id: str | None = None) -> dict[str, Any]:
        """Importa um workspace a partir de um ZIP de exportação.

        **Use quando:** Restaurar um backup ou trazer um workspace de outra connection.
        **Retorna:** {status: ok, id, name, ...} do workspace criado.
        **Exemplo:** workspace_import(file_path="exports/python_learning.zip",
            connection_id="postgres_prod")
        **Notas:** Cria um workspace novo; falha se o nome já existir. connection_id: opcional; sem
            ele usa a connection default (sqlite_local).
        """
        ws = ImportExportService(connection_id=connection_id).import_workspace(file_path)
        return {"status": "ok", **WorkspaceResponse.model_validate(ws).model_dump(mode="json")}
