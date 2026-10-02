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
    def artifact_attach(item_id: str, file_path: str) -> dict[str, Any]:
        """Anexa um arquivo local a um item (o arquivo é copiado para o armazenamento)."""
        data = ArtifactCreate(item_id=item_id, file_path=file_path)
        art = ArtifactService().attach(data.item_id, data.file_path)
        return ArtifactResponse.model_validate(art).model_dump(mode="json")

    @mcp.tool()
    def artifact_list(item_id: str) -> list[dict[str, Any]]:
        """Lista os artifacts de um item."""
        rows = ArtifactService().list(item_id)
        return ArtifactListResponse.model_validate(rows).model_dump(mode="json")

    @mcp.tool()
    def artifact_get(artifact_id: str) -> dict[str, Any]:
        """Obtém metadados e conteúdo (base64) de um artifact."""
        art, content = ArtifactService().get(artifact_id)
        return {
            "artifact": ArtifactResponse.model_validate(art).model_dump(mode="json"),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
