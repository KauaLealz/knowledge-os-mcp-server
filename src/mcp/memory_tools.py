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


def memory_promote(
    item_id: str, target_memory: str, connection_id: str | None = None
) -> dict[str, Any]:
    """Promove um item para uma classe de memória superior.

    **Use quando:** Quando conhecimento temporário se provou útil e deve durar mais.
    **Retorna:** Item atualizado (novo memory_class).
    **Exemplo:** memory_promote(item_id="item_def456", target_memory="longterm")
    **Notas:** Ordem crescente: ephemeral, working, longterm, canonical. Nunca rebaixa nem volta a
        ephemeral; ao sair de ephemeral o ttl_days é removido. connection_id: opcional; sem ele usa
        a connection default (a do JSON).
    """
    req = MemoryPromoteRequest(item_id=item_id, target_memory=target_memory)  # type: ignore[arg-type]
    item = MemoryService(connection_id=connection_id).promote(req.item_id, req.target_memory)
    return MemoryResponse.model_validate(item).model_dump(mode="json")


def memory_renew(item_id: str, ttl_days: int, connection_id: str | None = None) -> dict[str, Any]:
    """Renova o TTL de um item ephemeral.

    **Use quando:** Evitar que um item temporário expire enquanto ainda é relevante.
    **Retorna:** Item atualizado (novo ttl_days).
    **Exemplo:** memory_renew(item_id="item_def456", ttl_days=14)
    **Notas:** Só vale para items ephemeral; ttl_days deve ser positivo. connection_id: opcional;
        sem ele usa a connection default (a do JSON).
    """
    req = MemoryRenewRequest(item_id=item_id, ttl_days=ttl_days)
    item = MemoryService(connection_id=connection_id).renew(req.item_id, req.ttl_days)
    return MemoryResponse.model_validate(item).model_dump(mode="json")


def register(mcp: FastMCP) -> None:
    """Registra as 2 tools de memória no FastMCP."""
    for fn in (memory_promote, memory_renew):
        mcp.tool()(fn)
