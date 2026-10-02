"""MCP tools: tags."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.tag_schemas import TagCreate, TagListResponse, TagResponse
from src.services.tag_service import TagService

logger = logging.getLogger(__name__)


def tag_create(name: str) -> dict[str, Any]:
    """Cria nova tag."""
    req = TagCreate(name=name)
    tag = TagService().create(req.name)
    return TagResponse.model_validate(tag).model_dump(mode="json")


def tag_list() -> list[dict[str, Any]]:
    """Lista todas as tags."""
    tags = TagService().list()
    return TagListResponse.model_validate(tags, from_attributes=True).model_dump(mode="json")


def tag_delete(tag_id: str) -> dict[str, str]:
    """Deleta tag (e remove dos items)."""
    TagService().delete(tag_id)
    return {"status": "ok", "message": f"Tag removida: {tag_id}"}


def register(mcp: FastMCP) -> None:
    """Registra as 3 tools de tag no FastMCP."""
    for fn in (tag_create, tag_list, tag_delete):
        mcp.tool()(fn)
