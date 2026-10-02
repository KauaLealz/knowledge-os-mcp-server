"""MCP tools: tags."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.tag_schemas import TagCreate, TagListResponse, TagResponse
from src.services.tag_service import TagService

logger = logging.getLogger(__name__)


def tag_create(name: str, connection_id: str | None = None) -> dict[str, Any]:
    """Cria uma tag (string livre) no catálogo da connection.

    **Use quando:** Preparar um vocabulário de tags; tags também podem ser passadas direto em
        item_create.
    **Retorna:** {id, name}.
    **Exemplo:** tag_create(name="asyncio")
    **Notas:** Tags são livres e criadas dinamicamente. connection_id: opcional; sem ele usa a
        connection default (sqlite_local).
    """
    req = TagCreate(name=name)
    tag = TagService(connection_id=connection_id).create(req.name)
    return TagResponse.model_validate(tag).model_dump(mode="json")


def tag_list(connection_id: str | None = None) -> list[dict[str, Any]]:
    """Lista todas as tags da connection.

    **Use quando:** Ver o vocabulário existente para reutilizar tags em vez de criar variantes.
    **Retorna:** Lista de {id, name}.
    **Exemplo:** tag_list()
    **Notas:** connection_id: opcional; sem ele usa a connection default (sqlite_local).
    """
    tags = TagService(connection_id=connection_id).list()
    return TagListResponse.model_validate(tags, from_attributes=True).model_dump(mode="json")


def tag_delete(tag_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Deleta uma tag e a remove de todos os items.

    **Use quando:** Limpar tags obsoletas ou duplicadas.
    **Retorna:** {status: ok, message}.
    **Exemplo:** tag_delete(tag_id="tag_123")
    **Notas:** Os items permanecem; só a associação some. connection_id: opcional; sem ele usa a
        connection default (sqlite_local).
    """
    TagService(connection_id=connection_id).delete(tag_id)
    return {"status": "ok", "message": f"Tag removida: {tag_id}"}


def register(mcp: FastMCP) -> None:
    """Registra as 3 tools de tag no FastMCP."""
    for fn in (tag_create, tag_list, tag_delete):
        mcp.tool()(fn)
