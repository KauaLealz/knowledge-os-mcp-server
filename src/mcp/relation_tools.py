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


def relation_create(
    source_id: str, target_id: str, relation_type: str, connection_id: str | None = None
) -> dict[str, Any]:
    """Cria uma relação semântica entre dois items.

    **Use quando:** Registrar dependências, implementações, substituições ou referências entre
        conhecimentos.
    **Retorna:** {id, source_item_id, target_item_id, relation_type, created_at}.
    **Exemplo:** relation_create(source_id="item_A", target_id="item_B", relation_type="depends_on")
    **Notas:** Tipos: related_to, depends_on, implements, references, supersedes, derived_from. A
        direção importa: source_id é quem depende/implementa/referencia target_id. connection_id:
        opcional; sem ele usa a connection default (sqlite_local).
    """
    req = RelationCreate(
        source_item_id=source_id, target_item_id=target_id, relation_type=relation_type  # type: ignore[arg-type]
    )
    rel = RelationService(connection_id=connection_id).create(
        req.source_item_id, req.target_item_id, req.relation_type
    )
    return RelationResponse.model_validate(rel).model_dump(mode="json")


def relation_list(item_id: str, connection_id: str | None = None) -> list[dict[str, Any]]:
    """Lista as relações de um item (como origem ou destino).

    **Use quando:** Navegar pelo grafo de conhecimento a partir de um item.
    **Retorna:** Lista de relações (id, source_item_id, target_item_id, relation_type).
    **Exemplo:** relation_list(item_id="item_A")
    **Notas:** connection_id: opcional; sem ele usa a connection default (sqlite_local).
    """
    rels = RelationService(connection_id=connection_id).list(item_id)
    return RelationListResponse.model_validate(rels, from_attributes=True).model_dump(mode="json")


def relation_delete(relation_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Remove uma relação pelo id.

    **Use quando:** Desfazer uma relação criada por engano ou que deixou de valer.
    **Retorna:** {status: ok, message}.
    **Exemplo:** relation_delete(relation_id="rel_123")
    **Notas:** Use o id obtido em relation_list. Os items não são afetados. connection_id: opcional;
        sem ele usa a connection default (sqlite_local).
    """
    RelationService(connection_id=connection_id).delete(relation_id)
    return {"status": "ok", "message": f"Relação removida: {relation_id}"}


def register(mcp: FastMCP) -> None:
    """Registra as 3 tools de relação no FastMCP."""
    for fn in (relation_create, relation_list, relation_delete):
        mcp.tool()(fn)
