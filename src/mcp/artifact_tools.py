"""Tools MCP de Artifact."""

import base64
import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.artifact_schemas import ArtifactCreate, ArtifactListResponse, ArtifactResponse
from src.services.artifact_service import ArtifactService

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Registra as 3 tools de artifact no servidor."""

    @mcp.tool()
    def artifact_attach(
        item_id: str, file_path: str, connection_id: str | None = None
    ) -> dict[str, Any]:
        """Anexa um arquivo local a um item (o arquivo é copiado para o armazenamento).

        **Use quando:** Guardar documento, imagem ou código junto do conhecimento que o descreve.
        **Retorna:** {id, item_id, filename, file_size, mime_type, created_at} do artifact.
        **Exemplo:** artifact_attach(item_id="item_def456", file_path="C:/docs/diagrama.png")
        **Notas:** Máximo de 100MB por arquivo; o caminho deve ser um arquivo regular existente.
            connection_id: opcional; sem ele usa a connection default (`default`).
        """
        data = ArtifactCreate(item_id=item_id, file_path=file_path)
        art = ArtifactService(connection_id=connection_id).attach(data.item_id, data.file_path)
        return ArtifactResponse.model_validate(art).model_dump(mode="json")

    @mcp.tool()
    def artifact_list(item_id: str, connection_id: str | None = None) -> list[dict[str, Any]]:
        """Lista os artifacts de um item.

        **Use quando:** Ver os anexos de um item antes de baixar algum.
        **Retorna:** Lista de artifacts (id, filename, file_size, ...), sem o conteúdo.
        **Exemplo:** artifact_list(item_id="item_def456")
        **Notas:** connection_id: opcional; sem ele usa a connection default (`default`).
        """
        rows = ArtifactService(connection_id=connection_id).list(item_id)
        return ArtifactListResponse.model_validate(rows).model_dump(mode="json")

    @mcp.tool()
    def artifact_get(artifact_id: str, connection_id: str | None = None) -> dict[str, Any]:
        """Obtém metadados e conteúdo de um artifact.

        **Use quando:** Recuperar o arquivo anexado.
        **Retorna:** {artifact: metadados, content_base64: conteúdo em base64}.
        **Exemplo:** artifact_get(artifact_id="art_123")
        **Notas:** Arquivos grandes geram resposta grande: confira file_size com artifact_list
            antes. connection_id: opcional; sem ele usa a connection default (`default`).
        """
        art, content = ArtifactService(connection_id=connection_id).get(artifact_id)
        return {
            "artifact": ArtifactResponse.model_validate(art).model_dump(mode="json"),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
