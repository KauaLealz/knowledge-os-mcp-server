"""Ferramentas do segundo cérebro para agentes: projeto, contexto e escrita em lote."""

from typing import Any

from fastmcp import FastMCP

from src.schemas.item_schemas import ItemResponse
from src.services.context_service import ContextService
from src.services.item_service import ItemService
from src.services.project_service import ProjectService


def project_link(
    project: str, workspace: str, domain: str, connection_id: str | None = None
) -> dict[str, str]:
    """Liga um repositório a um workspace/domain do segundo cérebro.

    **Use quando:** Configurar um projeto pela primeira vez (o /plumb-setup faz isso).
    **Retorna:** {project_key, workspace, domain}.
    **Exemplo:** project_link(project="C:/Projects/app", workspace="Polara", domain="app")
    **Notas:** project aceita caminho (qualquer pasta do repo), URL do remote ou chave. A chave
        é o remote do git normalizado (ou o caminho, sem remote). Workspace e domain são criados
        se não existirem. Religar move o projeto.
    """
    return ProjectService(connection_id=connection_id).link(project, workspace, domain)


def context_get(
    project: str,
    paths: list[str] | None = None,
    query: str | None = None,
    budget_tokens: int = 1500,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Pacote de contexto do projeto: regras, contexto, decisões, padrões, procedimentos.

    **Use quando:** Começar a trabalhar num projeto (se o hook não injetou) ou ao passar a
        mexer em arquivos de outra área (passe `paths` para trazer as regras com escopo).
    **Retorna:** {linked, project_key, workspace, domain, markdown, included, omitted}.
    **Exemplo:** context_get(project=".", paths=["src/payments/Charge.java"], query="estorno")
    **Notas:** Só títulos, resumos e chaves, dentro de `budget_tokens`; para o texto completo,
        item_get(key=..., project=...). Inclui o domain do projeto, o domain `Geral` do
        workspace e `Global/Geral`. Omite substituídos, obsoletos e ephemeral.
    """
    return ContextService(connection_id=connection_id).build(project, paths, query, budget_tokens)


def item_upsert(
    key: str,
    workspace: str | None = None,
    domain: str | None = None,
    project: str | None = None,
    type: str | None = None,
    memory_class: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    content: str | None = None,
    keywords: str | None = None,
    source: str | None = None,
    scope_paths: list[str] | None = None,
    tags: list[str] | None = None,
    labels: list[str] | None = None,
    confidence: int | None = None,
    importance: int | None = None,
    ttl_days: int | None = None,
    status: str | None = None,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Cria ou atualiza o item de `key` (sem duplicar). Forma preferida de gravar.

    **Use quando:** Guardar ou corrigir uma regra, decisão, procedimento ou aprendizado.
    **Retorna:** {action: created|updated|unchanged, item}.
    **Exemplo:** item_upsert(key="regra/money", project=".", type="rule",
        memory_class="working", title="Money em pagamentos", summary="Valores em Money",
        content="...", scope_paths=["src/payments/**"], source="PAY-142")
    **Notas:** Informe project (o domain ligado) ou workspace+domain (criados se não
        existirem). Na criação valem os obrigatórios de item_create. memory_class só sobe.
        Conteúdo com cara de segredo é recusado.
    """
    svc = ItemService(connection_id=connection_id)
    ws_id, dm_id = _location(svc, workspace, domain, project, connection_id)
    fields = dict(
        type=type, memory_class=memory_class, title=title, summary=summary, content=content,
        keywords=keywords, source=source, scope_paths=scope_paths, tags=tags, labels=labels,
        confidence=confidence, importance=importance, ttl_days=ttl_days, status=status,
    )
    item, action = svc.upsert(ws_id, dm_id, key, **fields)
    return {"action": action, "item": ItemResponse.from_item(item).model_dump(mode="json")}


def item_batch_upsert(
    items: list[dict[str, Any]], project: str | None = None, connection_id: str | None = None
) -> list[dict[str, str]]:
    """Grava vários itens numa transação (o fechamento de uma mudança, uma importação).

    **Use quando:** Gravar de uma vez o que o curador propôs ao fechar uma mudança.
    **Retorna:** [{key, id, action}] na ordem recebida.
    **Exemplo:** item_batch_upsert(project=".", items=[{"key": "decisao/pix-recusa",
        "type": "insight", "memory_class": "working", "title": "...", "summary": "...",
        "content": "...", "source": "PAY-142"}])
    **Notas:** Cada item usa os campos de item_upsert. Sem workspace/domain no item, vale o
        domain ligado a `project`. Um erro desfaz o lote inteiro e aponta a entrada.
    """
    if project:
        link = ProjectService(connection_id=connection_id).require(project)
        items = [{"workspace": link["workspace"], "domain": link["domain"], **i} for i in items]
    return ItemService(connection_id=connection_id).batch_upsert(items)


def _location(
    svc: ItemService,
    workspace: str | None,
    domain: str | None,
    project: str | None,
    connection_id: str | None,
) -> tuple[str, str]:
    if workspace and domain:
        return svc.ensure_location(workspace, domain)
    if project:
        link = ProjectService(connection_id=connection_id).require(project)
        return link["workspace_id"], link["domain_id"]
    from src.exceptions import ValidationError

    raise ValidationError("Informe project ou workspace e domain")


def register(mcp: FastMCP) -> None:
    """Registra as ferramentas do segundo cérebro."""
    for fn in (project_link, context_get, item_upsert, item_batch_upsert):
        mcp.tool()(fn)
