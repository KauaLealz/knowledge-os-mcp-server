"""Tools MCP para Items: create, update, delete, get e search."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.db.session import get_engine
from src.exceptions import ValidationError
from src.schemas.item_schemas import ItemResponse, ItemSearchRequest, ItemSearchResult
from src.schemas.relation_schemas import RelationListResponse
from src.services.item_service import ItemService
from src.services.project_service import ProjectService
from src.services.relation_service import RelationService

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
        key: str | None = None,
        keywords: str | None = None,
        source: str | None = None,
        scope_paths: list[str] | None = None,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Cria um item de conhecimento (a unidade principal do sistema).

        **Use quando:** Registrar uma regra, padrão, procedimento, insight ou conhecimento que deve
            ser reutilizado depois. Com `key`, prefira item_upsert (não duplica).
        **Retorna:** Item completo; sem `key`, inclui `similar` com itens de título parecido.
        **Exemplo:** item_create(workspace="Python Learning", domain="Decorators", type="knowledge",
            memory_class="longterm", title="O que é um decorator?", summary="Açúcar sintático para
            funções de alta ordem", content="# Decorators ...", tags=["python"])
        **Notas:** workspace e domain aceitam nome ou id. type: context, rule, pattern, procedure,
            knowledge, insight, artifact, task. memory_class: ephemeral (exige ttl_days), working,
            longterm, canonical. confidence 0-100, importance 0-10. keywords: sinônimos para a
            busca. scope_paths: globs onde uma regra vale. Segredos são recusados.
        """
        svc = _service(connection_id)
        workspace_id = svc.resolve_workspace_id(workspace)
        domain_id = svc.resolve_domain_id(workspace_id, domain)
        similar = [] if key else svc.similar(workspace_id, title)
        item = svc.create(
            workspace_id=workspace_id, domain_id=domain_id, type=type,
            memory_class=memory_class, title=title, summary=summary, content=content,
            tags=tags, labels=labels, confidence=confidence, importance=importance,
            ttl_days=ttl_days, key=key, keywords=keywords, source=source,
            scope_paths=scope_paths,
        )
        data = ItemResponse.from_item(item).model_dump(mode="json")
        if similar:
            data["similar"] = similar
        return data

    @mcp.tool()
    def item_update(
        item_id: str,
        title: str | None = None,
        summary: str | None = None,
        content: str | None = None,
        confidence: int | None = None,
        importance: int | None = None,
        ttl_days: int | None = None,
        keywords: str | None = None,
        source: str | None = None,
        status: str | None = None,
        scope_paths: list[str] | None = None,
        tags: list[str] | None = None,
        labels: list[str] | None = None,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza campos de um item existente.

        **Use quando:** Corrigir ou complementar conhecimento já guardado.
        **Retorna:** Item completo atualizado.
        **Exemplo:** item_update(item_id="item_def456", summary="Novo resumo", importance=8)
        **Notas:** Só os campos informados mudam; tags e labels informadas substituem as atuais.
            status: active, superseded, deprecated. Para subir a classe de memória use
            memory_promote.
        """
        fields = {
            k: v
            for k, v in dict(
                title=title, summary=summary, content=content, confidence=confidence,
                importance=importance, ttl_days=ttl_days, keywords=keywords, source=source,
                status=status, scope_paths=scope_paths, tags=tags, labels=labels,
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
            connection_id: opcional; sem ele usa a connection default (`default`).
        """
        _service(connection_id).delete(item_id)
        return {"status": "ok", "message": f"Item {item_id} removido"}

    @mcp.tool()
    def item_get(
        item_id: str | None = None,
        key: str | None = None,
        project: str | None = None,
        workspace: str | None = None,
        domain: str | None = None,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Obtém um item completo, incluindo content, por id ou por key.

        **Use quando:** Ler o conteúdo de um resultado de item_search ou de context_get.
        **Retorna:** Item completo (content, tags, labels, metadados, relations).
        **Exemplo:** item_get(item_id="item_def456") · item_get(key="regra/money", project=".")
        **Notas:** Com key, informe project (o domain ligado) ou workspace e domain.
        """
        svc = _service(connection_id)
        if item_id:
            item = svc.get(item_id)
        elif key:
            if project:
                link = ProjectService(connection_id=connection_id).require(project)
                domain_id = link["domain_id"]
            elif workspace and domain:
                domain_id = svc.resolve_domain_id(svc.resolve_workspace_id(workspace), domain)
            else:
                raise ValidationError("Com key, informe project ou workspace e domain")
            item = svc.get_by_key(domain_id, key)
        else:
            raise ValidationError("Informe item_id ou key")
        data = ItemResponse.from_item(item).model_dump(mode="json")
        rels = RelationService(connection_id=connection_id).list(item.id)
        data["relations"] = RelationListResponse.model_validate(
            rels, from_attributes=True
        ).model_dump(mode="json")
        return data

    @mcp.tool()
    def item_search(
        query: str = "",
        workspace: str | None = None,
        domain: str | None = None,
        project: str | None = None,
        types: list[str] | None = None,
        memory_classes: list[str] | None = None,
        limit: int = 10,
        include_inactive: bool = False,
        connection_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Busca por texto (principal ferramenta de consulta).

        **Use quando:** Encontrar conhecimento por assunto; ponto de partida para ler algo já
            guardado.
        **Retorna:** Lista de {id, key, type, memory_class, domain, title, summary, score}.
            Nunca inclui content.
        **Exemplo:** item_search(query="migração flyway", project=".", limit=5)
        **Notas:** Sem workspace nem project, busca em todos os workspaces. project restringe ao
            workspace ligado. Ordena por relevância; acentos e plurais não atrapalham.
            include_inactive traz também substituídos, obsoletos e ephemeral vencidos.
        """
        svc = _service(connection_id)
        workspace_id = domain_id = None
        if project:
            workspace_id = ProjectService(connection_id=connection_id).require(project)[
                "workspace_id"
            ]
        elif workspace:
            workspace_id = svc.resolve_workspace_id(workspace)
        if domain:
            if workspace_id is None:
                raise ValidationError("domain exige workspace ou project")
            domain_id = svc.resolve_domain_id(workspace_id, domain)
        req = ItemSearchRequest(
            workspace_id=workspace_id, domain_id=domain_id, query=query, types=types,
            memory_classes=memory_classes, limit=limit,
        )
        rows = svc.search(
            req.workspace_id, req.domain_id, req.query, req.types, req.memory_classes, req.limit,
            include_inactive=include_inactive,
        )
        return [ItemSearchResult(**r).model_dump() for r in rows]
