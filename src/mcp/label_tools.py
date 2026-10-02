"""MCP tools: labels."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.label_schemas import LabelCreate, LabelListResponse, LabelResponse
from src.services.label_service import LabelService

logger = logging.getLogger(__name__)


def label_create(name: str) -> dict[str, Any]:
    """Cria nova label."""
    req = LabelCreate(name=name)
    label = LabelService().create(req.name)
    return LabelResponse.model_validate(label).model_dump(mode="json")


def label_list() -> list[dict[str, Any]]:
    """Lista todas as labels."""
    labels = LabelService().list()
    return LabelListResponse.model_validate(labels, from_attributes=True).model_dump(mode="json")


def label_delete(label_id: str) -> dict[str, str]:
    """Deleta label (e remove dos items)."""
    LabelService().delete(label_id)
    return {"status": "ok", "message": f"Label removida: {label_id}"}


def register(mcp: FastMCP) -> None:
    """Registra as 3 tools de label no FastMCP."""
    for fn in (label_create, label_list, label_delete):
        mcp.tool()(fn)
