"""Ferramentas do perfil `agent`: ler o contexto, buscar, ler itens, gravar, ligar projeto.

Cinco ferramentas cobrem o fluxo inteiro (o `health_check` fica no main). Escrita é uma
só (`item_save`), em lote e idempotente: é o que deixa o fechamento de uma mudança numa
chamada só e evita itens duplicados.
"""

from typing import Any

from fastmcp import FastMCP

from src.exceptions import NotFoundError, ValidationError
from src.schemas.item_schemas import ItemResponse, ItemSearchRequest, ItemSearchResult
from src.schemas.relation_schemas import RelationListResponse
from src.services.artifact_service import ArtifactService
from src.services.context_service import ContextService
from src.services.item_service import ItemService
from src.services.project_service import ProjectService
from src.services.relation_service import RelationService

MAX_GET = 20


def context_get(
    project: str,
    paths: list[str] | None = None,
    query: str | None = None,
    budget_tokens: int = 1500,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Pacote de contexto do projeto: regras, contexto, decisões, padrões, procedimentos.

    **Use quando:** Começar num projeto (se o hook não injetou) ou ao passar a mexer em outra
        área: `paths` traz as regras com escopo daqueles arquivos; `query`, itens relacionados.
    **Retorna:** {linked, project_key, workspace, domain, markdown, included, omitted, sensitive}.
    **Exemplo:** context_get(project=".", paths=["src/payments/Charge.java"], query="estorno")
    **Notas:** Dentro de `budget_tokens`. Itens que casam com `paths` ou `query` vêm em foco, com o
        começo do content (dispensa item_get); o resto, só título, resumo e key. `sensitive` é true
        se `paths` toca uma área marcada com a keyword "sensivel". Inclui o domain do projeto,
        `Geral` do workspace e `Global/Geral`. Sem substituídos, obsoletos nem ephemeral.
    """
    return ContextService(connection_id=connection_id).build(project, paths, query, budget_tokens)


def item_search(
    query: str = "",
    project: str | None = None,
    workspace: str | None = None,
    domain: str | None = None,
    types: list[str] | None = None,
    memory_classes: list[str] | None = None,
    limit: int = 10,
    include_inactive: bool = False,
    everywhere: bool = False,
    connection_id: str | None = None,
) -> list[dict[str, Any]]:
    """Busca por texto. Devolve resumos, nunca o conteúdo completo.

    **Use quando:** Procurar algo que pode já estar guardado (decisão, gotcha, procedimento).
    **Retorna:** [{id, key, type, memory_class, domain, title, summary, score, uses}].
    **Exemplo:** item_search(query="migração flyway", limit=5)
    **Notas:** Sem project/workspace, busca no projeto da pasta atual (se ligado) — não vaza para
        outros projetos; `everywhere=True` busca em todos. Relevância primeiro; acentos e plurais
        não atrapalham. include_inactive traz substituídos, obsoletos e ephemeral vencidos.
    """
    svc = ItemService(connection_id=connection_id)
    workspace_id = domain_id = None
    if not project and not workspace and not everywhere:
        project = "." if ProjectService(connection_id=connection_id).resolve(".") else None
    if project:
        workspace_id = ProjectService(connection_id=connection_id).require(project)["workspace_id"]
    elif workspace:
        workspace_id = svc.resolve_workspace_id(workspace)
    if domain:
        if workspace_id is None:
            raise ValidationError("domain exige project ou workspace")
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


def item_get(
    ids: list[str] | None = None,
    keys: list[str] | None = None,
    project: str | None = None,
    workspace: str | None = None,
    domain: str | None = None,
    connection_id: str | None = None,
) -> list[dict[str, Any]]:
    """Lê itens completos (content, tags, relações, anexos) por id e/ou key, vários de uma vez.

    **Use quando:** O resumo da busca ou do contexto não bastou.
    **Retorna:** Lista de itens completos, na ordem pedida; o que não existe vem como
        {key|id, missing: true}, sem derrubar os outros.
    **Exemplo:** item_get(keys=["regra/money", "proc/deploy"], project=".")
    **Notas:** keys exigem project (o domain ligado) ou workspace e domain. Até 20 por chamada.
    """
    ids, keys = ids or [], keys or []
    if not ids and not keys:
        raise ValidationError("Informe ids ou keys")
    if len(ids) + len(keys) > MAX_GET:
        raise ValidationError(f"No máximo {MAX_GET} itens por chamada")
    svc = ItemService(connection_id=connection_id)

    def fetch(getter: Any, ref: dict[str, str]) -> Any:
        try:
            return getter()
        except NotFoundError:
            return {**ref, "missing": True}

    items = [fetch(lambda i=i: svc.get(i), {"id": i}) for i in ids]
    if keys:
        if project:
            domain_id = ProjectService(connection_id=connection_id).require(project)["domain_id"]
        elif workspace and domain:
            domain_id = svc.resolve_domain_id(svc.resolve_workspace_id(workspace), domain)
        else:
            raise ValidationError("keys exigem project ou workspace e domain")
        items += [fetch(lambda k=k: svc.get_by_key(domain_id, k), {"key": k}) for k in keys]
    out: list[dict[str, Any]] = []
    relations = RelationService(connection_id=connection_id)
    artifacts = ArtifactService(connection_id=connection_id)
    for item in items:
        if isinstance(item, dict):
            out.append(item)
            continue
        data = ItemResponse.from_item(item).model_dump(mode="json")
        data["relations"] = RelationListResponse.model_validate(
            relations.list(item.id), from_attributes=True
        ).model_dump(mode="json")
        data["artifacts"] = [
            {"id": a.id, "filename": a.filename, "file_size": a.file_size}
            for a in artifacts.list(item.id)
        ]
        out.append(data)
    return out


def item_save(
    items: list[dict[str, Any]], project: str | None = None, connection_id: str | None = None
) -> list[dict[str, Any]]:
    """Grava itens (criar, atualizar, upsert, promover, renovar, relacionar) numa transação.

    **Use quando:** Guardar o que vale para depois — uma regra que o usuário enunciou, as
        decisões e aprendizados ao fechar uma mudança, uma correção de um item.
    **Retorna:** [{index, id, key, action: created|updated|unchanged, similar?, relations?}].
    **Modo, por entrada:** com `key` → upsert no domain (não duplica; o preferido); com `id` →
        atualiza o item; sem os dois → cria e devolve `similar` (títulos parecidos já guardados).
    **Exemplo (upsert):** item_save(project=".", items=[{"key": "regra/money", "type": "rule",
        "memory_class": "working", "title": "Money em pagamentos", "summary": "Valores em Money,
        nunca double", "content": "...", "scope_paths": ["src/payments/**"], "source": "PAY-142"}])
    **Exemplo (atualizar e promover):** item_save(items=[{"id": "...", "summary": "...",
        "memory_class": "longterm"}])
    **Exemplo (substituir):** item_save(project=".", items=[{"key": "proc/deploy-v2", ...,
        "relations": [{"type": "supersedes", "target": "proc/deploy"}]}])
    **Campos:** type (rule, insight, procedure, pattern, knowledge, context, artifact, task),
        memory_class (ephemeral c/ ttl_days, working, longterm, canonical — só sobe), title,
        summary, content, keywords, source, scope_paths, tags, labels, confidence 0-100,
        importance 0-10, ttl_days (renova), status (active, superseded, deprecated), relations
        [{type: related_to|depends_on|implements|references|supersedes|derived_from, target: id
        ou key}], workspace/domain (sem eles vale o domain ligado a `project`).
    **Notas:** Um erro desfaz o lote e aponta a entrada. Conteúdo com cara de segredo é recusado.
    """
    default = None
    if project:
        link = ProjectService(connection_id=connection_id).require(project)
        default = (link["workspace_id"], link["domain_id"])
    return ItemService(connection_id=connection_id).save(items, default_location=default)


def project_link(
    project: str, workspace: str, domain: str, connection_id: str | None = None
) -> dict[str, str]:
    """Liga um repositório a um workspace/domain do segundo cérebro.

    **Use quando:** Configurar um projeto pela primeira vez (o /plumb-setup faz isso).
    **Retorna:** {project_key, workspace, domain}.
    **Exemplo:** project_link(project=".", workspace="Polara", domain="projpro")
    **Notas:** project aceita caminho (qualquer pasta do repo), URL do remote ou chave; a chave é
        o remote do git normalizado (ou o caminho, sem remote). Workspace e domain são criados se
        não existirem. Religar move o projeto.
    """
    return ProjectService(connection_id=connection_id).link(project, workspace, domain)


def register(mcp: FastMCP) -> None:
    """Registra as ferramentas do perfil agent."""
    for fn in (context_get, item_search, item_get, item_save, project_link):
        mcp.tool()(fn)
