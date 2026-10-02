"""MCP tools: relações entre items."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.relation_schemas import (
    RelationCreate,
    RelationListResponse,
    RelationResponse,
)
from src.services.relation_service import RelationService

logger = logging.getLogger(__name__)


def relation_create(source_id: str, target_id: str, relation_type: str) -> dict[str, Any]:
    """Cria relação entre items.

    Tipos: related_to, depends_on, implements, references, supersedes, derived_from.
    """
    req = RelationCreate(
        source_item_id=source_id, target_item_id=target_id, relation_type=relation_type  # type: ignore[arg-type]
    )
    rel = RelationService().create(req.source_item_id, req.target_item_id, req.relation_type)
    return RelationResponse.model_validate(rel).model_dump(mode="json")


def relation_list(item_id: str) -> list[dict[str, Any]]:
    """Lista relações de um item (como source ou target)."""
    rels = RelationService().list(item_id)
    return RelationListResponse.model_validate(rels, from_attributes=True).model_dump(mode="json")


def relation_delete(relation_id: str) -> dict[str, str]:
    """Deleta relação."""
    RelationService().delete(relation_id)
    return {"status": "ok", "message": f"Relação removida: {relation_id}"}


def register(mcp: FastMCP) -> None:
    """Registra as 3 tools de relação no FastMCP."""
    for fn in (relation_create, relation_list, relation_delete):
        mcp.tool()(fn)
