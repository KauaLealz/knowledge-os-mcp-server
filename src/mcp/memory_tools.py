"""MCP tools: classes de memória."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.memory_schemas import (
    MemoryPromoteRequest,
    MemoryRenewRequest,
    MemoryResponse,
)
from src.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


def memory_promote(item_id: str, target_memory: str) -> dict[str, Any]:
    """Promove item para classe de memória superior (ephemeral > working > longterm > canonical)."""
    req = MemoryPromoteRequest(item_id=item_id, target_memory=target_memory)  # type: ignore[arg-type]
    item = MemoryService().promote(req.item_id, req.target_memory)
    return MemoryResponse.model_validate(item).model_dump(mode="json")


def memory_renew(item_id: str, ttl_days: int) -> dict[str, Any]:
    """Renova TTL de item ephemeral."""
    req = MemoryRenewRequest(item_id=item_id, ttl_days=ttl_days)
    item = MemoryService().renew(req.item_id, req.ttl_days)
    return MemoryResponse.model_validate(item).model_dump(mode="json")


def register(mcp: FastMCP) -> None:
    """Registra as 2 tools de memória no FastMCP."""
    for fn in (memory_promote, memory_renew):
        mcp.tool()(fn)
