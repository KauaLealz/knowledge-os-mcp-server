"""Tools MCP para Items: create, update, delete, get e search."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.db.session import get_engine
from src.schemas.item_schemas import ItemResponse, ItemSearchRequest, ItemSearchResult
from src.services.item_service import ItemService

logger = logging.getLogger(__name__)


def _service() -> ItemService:
    return ItemService(get_engine())


def register(mcp: FastMCP) -> None:
    """Registra as 5 tools de item no servidor FastMCP."""

    @mcp.tool()
    def item_create(
        workspace: str,
        domain: str,
        type: str,
        memory_class: str,
        title: str,
        summary: str,
        content: str,
        tags: list[str] | None = None,
        labels: list[str] | None = None,
        confidence: int | None = None,
        importance: int | None = None,
        ttl_days: int | None = None,
    ) -> dict[str, Any]:
        """Cria novo item de conhecimento.

        workspace e domain aceitam nome ou id. type: context, rule, pattern, procedure,
        knowledge, insight, artifact. memory_class: ephemeral (exige ttl_days), working,
        longterm, canonical. confidence 0-100, importance 0-10.
        """
        svc = _service()
        workspace_id = svc.resolve_workspace_id(workspace)
        domain_id = svc.resolve_domain_id(workspace_id, domain)
        item = svc.create(
            workspace_id=workspace_id, domain_id=domain_id, type=type,
            memory_class=memory_class, title=title, summary=summary, content=content,
            tags=tags, labels=labels, confidence=confidence, importance=importance,
            ttl_days=ttl_days,
        )
        return ItemResponse.from_item(item).model_dump(mode="json")

    @mcp.tool()
    def item_update(
        item_id: str,
        summary: str | None = None,
        content: str | None = None,
        confidence: int | None = None,
        importance: int | None = None,
        ttl_days: int | None = None,
    ) -> dict[str, Any]:
        """Atualiza item (summary, content, confidence, importance, ttl_days).

        Só os campos informados são alterados.
        """
        fields = {
            k: v
            for k, v in dict(
                summary=summary, content=content, confidence=confidence,
                importance=importance, ttl_days=ttl_days,
            ).items()
            if v is not None
        }
        item = _service().update(item_id, **fields)
        return ItemResponse.from_item(item).model_dump(mode="json")

    @mcp.tool()
    def item_delete(item_id: str) -> dict[str, str]:
        """Deleta item."""
        _service().delete(item_id)
        return {"status": "ok", "message": f"Item {item_id} removido"}

    @mcp.tool()
    def item_get(item_id: str) -> dict[str, Any]:
        """Obtém item completo (COM content)."""
        return ItemResponse.from_item(_service().get(item_id)).model_dump(mode="json")

    @mcp.tool()
    def item_search(
        workspace: str,
        domain: str | None = None,
        query: str = "",
        types: list[str] | None = None,
        memory_classes: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Busca items por FTS5 (principal ferramenta). Retorna id, title, summary, score.

        Nunca retorna content: use item_get para ler o conteúdo completo. Ordena por
        importance, confidence, access_count e updated_at (desc). workspace e domain
        aceitam nome ou id.
        """
        svc = _service()
        workspace_id = svc.resolve_workspace_id(workspace)
        domain_id = svc.resolve_domain_id(workspace_id, domain) if domain else None
        req = ItemSearchRequest(
            workspace_id=workspace_id, domain_id=domain_id, query=query, types=types,
            memory_classes=memory_classes, limit=limit,
        )
        rows = svc.search(
            req.workspace_id, req.domain_id, req.query, req.types, req.memory_classes, req.limit
        )
        return [ItemSearchResult(**r).model_dump() for r in rows]
