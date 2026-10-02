"""Tools MCP para Items: create, update, delete, get e search."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.db.session import get_engine
from src.schemas.item_schemas import ItemResponse, ItemSearchRequest, ItemSearchResult
from src.services.item_service import ItemService

logger = logging.getLogger(__name__)


def _service(connection_id: str | None = None) -> ItemService:
    return ItemService(get_engine(connection_id) if connection_id else get_engine())


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
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Cria um item de conhecimento (a unidade principal do sistema).

        **Use quando:** Registrar uma regra, padrão, procedimento, insight ou conhecimento que deve
            ser reutilizado depois.
        **Retorna:** Item completo (id, title, summary, content, type, memory_class, tags, labels,
            ...).
        **Exemplo:** item_create(workspace="Python Learning", domain="Decorators", type="knowledge",
            memory_class="longterm", title="O que é um decorator?", summary="Açúcar sintático para
            funções de alta ordem", content="# Decorators ...", tags=["python"])
        **Notas:** workspace e domain aceitam nome ou id. type: context, rule, pattern, procedure,
            knowledge, insight, artifact. memory_class: ephemeral (exige ttl_days), working,
            longterm, canonical. confidence 0-100, importance 0-10. connection_id: opcional; sem ele
            usa a connection default (sqlite_local).
        """
        svc = _service(connection_id)
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
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza campos de um item existente.

        **Use quando:** Corrigir ou complementar conhecimento já guardado.
        **Retorna:** Item completo atualizado.
        **Exemplo:** item_update(item_id="item_def456", summary="Novo resumo", importance=8)
        **Notas:** Só summary, content, confidence, importance e ttl_days são alteráveis, e só os
            informados mudam. Para mudar a classe de memória use memory_promote. connection_id:
            opcional; sem ele usa a connection default (sqlite_local).
        """
        fields = {
            k: v
            for k, v in dict(
                summary=summary, content=content, confidence=confidence,
                importance=importance, ttl_days=ttl_days,
            ).items()
            if v is not None
        }
        item = _service(connection_id).update(item_id, **fields)
        return ItemResponse.from_item(item).model_dump(mode="json")

    @mcp.tool()
    def item_delete(item_id: str, connection_id: str | None = None) -> dict[str, str]:
        """Deleta um item.

        **Use quando:** Remover conhecimento incorreto ou obsoleto.
        **Retorna:** {status: ok, message}.
        **Exemplo:** item_delete(item_id="item_def456")
        **Notas:** Destrutivo. Se o histórico importar, prefira uma relation supersedes.
            connection_id: opcional; sem ele usa a connection default (sqlite_local).
        """
        _service(connection_id).delete(item_id)
        return {"status": "ok", "message": f"Item {item_id} removido"}

    @mcp.tool()
    def item_get(item_id: str, connection_id: str | None = None) -> dict[str, Any]:
        """Obtém um item completo, incluindo content.

        **Use quando:** Ler o conteúdo de um resultado de item_search.
        **Retorna:** Item completo (content, tags, labels, metadados).
        **Exemplo:** item_get(item_id="item_def456")
        **Notas:** item_search nunca devolve content; use este tool para lê-lo. connection_id:
            opcional; sem ele usa a connection default (sqlite_local).
        """
        return ItemResponse.from_item(_service(connection_id).get(item_id)).model_dump(mode="json")

    @mcp.tool()
    def item_search(
        workspace: str,
        domain: str | None = None,
        query: str = "",
        types: list[str] | None = None,
        memory_classes: list[str] | None = None,
        limit: int = 10,
        connection_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Busca full-text de items em um workspace (principal ferramenta de consulta).

        **Use quando:** Encontrar conhecimento por assunto; ponto de partida para ler algo já
            guardado.
        **Retorna:** Lista de {id, title, summary, score}. Nunca inclui content.
        **Exemplo:** item_search(workspace="Python Learning", query="decorator",
            types=["knowledge"], limit=5)
        **Notas:** workspace é obrigatório (nome ou id); domain, types e memory_classes filtram.
            Ordena por importance, confidence, access_count e updated_at (desc). limit padrão 10.
            connection_id: opcional; sem ele usa a connection default (sqlite_local).
        """
        svc = _service(connection_id)
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
