"""Tools MCP de Domain. O workspace é identificado pelo nome."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.domain_schemas import DomainCreate, DomainListResponse, DomainResponse
from src.services.domain_service import DomainService
from src.services.import_export_service import ImportExportService
from src.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)


def _workspace_id(workspace: str, connection_id: str | None) -> str:
    """Resolve o nome do workspace para o id (NotFoundError se não existe)."""
    return WorkspaceService(connection_id=connection_id).get(workspace).id


def register(mcp: FastMCP) -> None:
    """Registra as 6 tools de domain no servidor."""

    @mcp.tool()
    def domain_create(
        workspace: str, name: str, description: str | None = None, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Cria um domain (tópico) dentro de um workspace.

        **Use quando:** Estruturar um workspace em tópicos antes de guardar items.
        **Retorna:** {id, workspace_id, name, description, ...}.
        **Exemplo:** domain_create(workspace="Python Learning", name="Decorators")
        **Notas:** workspace é informado pelo nome. Nome do domain único dentro do workspace.
            connection_id: opcional; sem ele usa a connection default (sqlite_local).
        """
        data = DomainCreate(
            workspace_id=_workspace_id(workspace, connection_id), name=name, description=description
        )
        dm = DomainService(connection_id=connection_id).create(
            data.workspace_id, data.name, data.description
        )
        return DomainResponse.model_validate(dm).model_dump(mode="json")

    @mcp.tool()
    def domain_list(workspace: str, connection_id: str | None = None) -> list[dict[str, Any]]:
        """Lista os domains de um workspace.

        **Use quando:** Ver os tópicos existentes antes de criar items.
        **Retorna:** Lista de domains.
        **Exemplo:** domain_list(workspace="Python Learning")
        **Notas:** workspace é o nome. connection_id: opcional; sem ele usa a connection default
            (sqlite_local).
        """
        rows = DomainService(connection_id=connection_id).list(
            _workspace_id(workspace, connection_id)
        )
        return DomainListResponse.model_validate(rows).model_dump(mode="json")

    @mcp.tool()
    def domain_get(workspace: str, name: str, connection_id: str | None = None) -> dict[str, Any]:
        """Obtém um domain pelo nome.

        **Use quando:** Confirmar que um domain existe ou ler sua descrição.
        **Retorna:** Dados do domain.
        **Exemplo:** domain_get(workspace="Python Learning", name="Decorators")
        **Notas:** Erro de not found se o nome não existir no workspace. connection_id: opcional;
            sem ele usa a connection default (sqlite_local).
        """
        dm = DomainService(connection_id=connection_id).get(
            _workspace_id(workspace, connection_id), name
        )
        return DomainResponse.model_validate(dm).model_dump(mode="json")

    @mcp.tool()
    def domain_delete(
        workspace: str, name: str, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Deleta um domain pelo nome.

        **Use quando:** Remover um tópico obsoleto.
        **Retorna:** {status: deleted|not_found, message}.
        **Exemplo:** domain_delete(workspace="Python Learning", name="Decorators")
        **Notas:** Destrutivo: afeta os items do domain. connection_id: opcional; sem ele usa a
            connection default (sqlite_local).
        """
        if DomainService(connection_id=connection_id).delete(
            _workspace_id(workspace, connection_id), name
        ):
            return {"status": "deleted", "message": f"Domain '{name}' removido"}
        return {"status": "not_found", "message": f"Domain '{name}' não existe"}

    @mcp.tool()
    def domain_export(
        workspace: str, name: str, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Exporta um domain (prepara os dados para ZIP).

        **Use quando:** Compartilhar ou fazer backup de um único tópico.
        **Retorna:** {status: ok, domain: dados do domain}.
        **Exemplo:** domain_export(workspace="Python Learning", name="Decorators")
        **Notas:** connection_id: opcional; sem ele usa a connection default (sqlite_local).
        """
        data = DomainService(connection_id=connection_id).export(
            _workspace_id(workspace, connection_id), name
        )
        return {"domain": data["domain_data"], "status": "ok"}

    @mcp.tool()
    def domain_import(
        workspace: str, file_path: str, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Importa um domain de um ZIP para um workspace.

        **Use quando:** Restaurar ou trazer um tópico exportado.
        **Retorna:** {status: ok, id, name, ...} do domain criado.
        **Exemplo:** domain_import(workspace="Python Learning", file_path="exports/decorators.zip")
        **Notas:** Falha se o domain já existir no workspace. connection_id: opcional; sem ele usa a
            connection default (sqlite_local).
        """
        dm = ImportExportService(connection_id=connection_id).import_domain(
            _workspace_id(workspace, connection_id), file_path
        )
        return {"status": "ok", **DomainResponse.model_validate(dm).model_dump(mode="json")}
