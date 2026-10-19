"""Ferramentas MCP do Knowledge OS (v6): 31 ferramentas (sem `item_feedback`).

Cada ferramenta é uma função fina sobre um serviço: resolve o repositório ligado (quando vem
`repo`), chama o serviço e devolve o dicionário dele sem remodelar. Os erros de validação dos
serviços já dizem como corrigir e passam como estão.

Repositório e alcance: `repo` (caminho, normalmente ".", remote ou chave) vira, por
`RepoService`, o link `{workspace_id, project_id, workspace, project}`. O `viewpoint` da
cadeia de alcance (por hierarquia, `Snapshot.reach`) é `(workspace_id, project_id)`; o
`default_location` do `item_save` é `(workspace, project)`. Repositório informado e não ligado
é erro com a chamada que resolve. Só `item_search` tenta a pasta atual sozinho (sem `repo`,
`workspace` nem `everywhere`): ligada, vale o project dela; senão só os globais, com
`suggestion`. `repo` informado e não ligado vale como sem `repo` (só nas buscas; as demais
ferramentas dão erro).

Todas aceitam `connection_id` (a conexão; sem ele, a padrão), menos `connection_*` e
`health_check`. `repo` agrupa link/list/unlink/sync por `action=`: é a chamada que o hook de
sessão, o `/plumb-setup` e a fila offline usam.
"""

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from knowledge_os import model
from knowledge_os.config import NO_CONNECTION_MESSAGE
from knowledge_os.exceptions import ConfigError, NotFoundError, ValidationError
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.graph import GraphService
from knowledge_os.services.item_service import SUGGESTION, ItemService
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.services.repo_service import RepoService, repo_key
from knowledge_os.services.subject_service import SubjectService
from knowledge_os.services.tag_service import TagService
from knowledge_os.services.workspace_service import WorkspaceService
from knowledge_os.storage.access import resolve_connection, sync_connection

# Ponto de vista da cadeia de alcance por hierarquia: (workspace_id, project_id) do repositório
# ligado; project_id pode faltar. (Antes vinha de `services.scope`, removido no v6.)
Viewpoint = tuple[str, str | None] | None

# --------------------------------------------------------------------------------------
# repositório ligado → viewpoint / default_location
# --------------------------------------------------------------------------------------


def _link(repo: str, connection_id: str | None) -> dict[str, str]:
    """O link do repositório; não ligado é erro que diz a chamada que resolve."""
    found = RepoService(connection_id=connection_id).resolve(repo)
    if found is None:
        raise NotFoundError(
            f"Repositório não ligado ao segundo cérebro: {repo_key(repo)}. Ligue com "
            f'repo(action="link", repo="{repo}") (ou /plumb-setup) e repita a chamada.'
        )
    return found


def _viewpoint(repo: str | None, connection_id: str | None) -> Viewpoint:
    if not repo:
        return None
    link = _link(repo, connection_id)
    return link["workspace_id"], link["project_id"]


def _row(rows: list[dict[str, Any]], row_id: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """A linha de `rows()` do que acabou de mudar (em modo PR ainda não existe: o básico)."""
    return next((r for r in rows if r["id"] == row_id), fallback)


def _fill(fn: Callable[..., Any], **values: str) -> None:
    """Põe na docstring os valores gerados de `model` (`<<NOME>>`), para nunca divergirem."""
    doc = fn.__doc__ or ""
    for name, value in values.items():
        doc = doc.replace(f"<<{name}>>", value)
    fn.__doc__ = doc


def _codes(values: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f"`{v}`" for v in values)


# --------------------------------------------------------------------------------------
# workspace / project / subject
# --------------------------------------------------------------------------------------


def workspace_list(connection_id: str | None = None) -> list[dict[str, Any]]:
    """Lista os workspaces (contexto de trabalho: empresa, cliente, Pessoal).

    **Use quando:** Ver o que já existe antes de criar, ligar um repositório ou organizar.
    **Retorna:** [{id, name, description, scope, scope_explicit, items, projects}] — `scope` é o
        que vale (sem explícito, `scoped`); `scope_explicit`, o gravado.
    **Exemplo:** workspace_list()
    """
    return WorkspaceService(connection_id=connection_id).rows()


def workspace_create(name: str, description: str | None = None,
                     connection_id: str | None = None) -> dict[str, Any]:
    """Cria um workspace (contexto de trabalho: empresa, cliente, Pessoal).

    **Use quando:** Começar um novo contexto de trabalho.
    **Retorna:** {id, name, description, items, projects}.
    **Exemplo:** workspace_create(name="Polara", description="cliente")
    **Erro comum:** nome repetido — use workspace_update ou workspace_merge.
    **Notas:** O alcance é por hierarquia — um item que mora no workspace vale para todos os
        projects dele. Não há `scope`.
    """
    svc = WorkspaceService(connection_id=connection_id)
    ws = svc.create(name, description)
    return _row(svc.rows(), ws.id, {"id": ws.id, "name": ws.name,
                                    "description": ws.description})


def workspace_update(name: str, new_name: str | None = None, description: str | None = None,
                     connection_id: str | None = None) -> dict[str, Any]:
    """Atualiza nome e/ou descrição de um workspace (o que vier None fica como está).

    **Use quando:** Renomear (religa os repositórios) ou descrever um workspace.
    **Retorna:** {id, name, description, items, projects}.
    **Exemplo:** workspace_update(name="Polara", new_name="Polara Tech")
    **Erro comum:** "Workspace não encontrado" — confira o nome com workspace_list().
    """
    svc = WorkspaceService(connection_id=connection_id)
    ws = svc.update(name, new_name, description)
    return _row(svc.rows(), ws.id, {"id": ws.id, "name": ws.name,
                                    "description": ws.description})


def workspace_merge(source: str, target: str,
                    connection_id: str | None = None) -> dict[str, Any]:
    """Unifica dois workspaces: move os projects de `source` para `target` (homônimos são
    mesclados, não duplicados), religa os repositórios e apaga `source`.

    **Use quando:** Dois workspaces acabaram duplicados (grafias diferentes do mesmo cliente).
    **Retorna:** {merged_projects, renamed_collisions}.
    **Exemplo:** workspace_merge(source="polara-antiga", target="Polara")
    """
    return WorkspaceService(connection_id=connection_id).merge(source, target)


def workspace_delete(name: str, confirm: bool = False,
                     connection_id: str | None = None) -> dict[str, Any]:
    """Remove um workspace com os projects e itens dele. Destrutivo.

    **Use quando:** O usuário pediu para remover um workspace que não serve mais.
    **Retorna:** sem `confirm` → {status: "preview", would_delete: {workspace, projects,
        items}} (nada muda); com `confirm=True` → {status: "deleted", workspace, projects,
        items}.
    **Exemplo:** workspace_delete(name="Teste") e, confirmado, workspace_delete(name="Teste",
        confirm=True)
    **Erro comum:** passar `confirm=True` sem mostrar a prévia ao usuário.
    """
    svc = WorkspaceService(connection_id=connection_id)
    ws = svc.get(name)
    row = _row(svc.rows(), ws.id, {"projects": 0, "items": 0})
    would = {"workspace": ws.name, "projects": row["projects"], "items": row["items"]}
    if not confirm:
        return {"status": "preview", "would_delete": would}
    svc.delete(ws.id)
    return {"status": "deleted", **would}


def project_list(workspace: str, connection_id: str | None = None) -> list[dict[str, Any]]:
    """Lista os projects de um workspace (project = um repositório; `Geral` guarda o que vale
    para os repositórios do workspace).

    **Use quando:** Ver o que já existe antes de criar, ligar um repositório ou organizar.
    **Retorna:** [{id, workspace_id, name, description, scope, scope_explicit, items,
        subjects: [nomes]}] — `scope` é o que vale (herdado do workspace se não explícito).
    **Exemplo:** project_list(workspace="Polara")
    """
    return ProjectService(connection_id=connection_id).rows(workspace)


def project_create(workspace: str, name: str, description: str | None = None,
                   connection_id: str | None = None) -> dict[str, Any]:
    """Cria um project dentro de um workspace (project = um repositório/sistema).

    **Use quando:** Organizar um repositório novo (o `repo(action="link")` também cria).
    **Retorna:** {id, workspace_id, name, description, items, subjects}.
    **Exemplo:** project_create(workspace="Polara", name="app")
    **Erro comum:** "Workspace não encontrado" — crie com workspace_create ou confira o nome.
    """
    svc = ProjectService(connection_id=connection_id)
    pj = svc.create(workspace, name, description)
    return _row(svc.rows(workspace), pj.id, {"id": pj.id, "name": pj.name,
                                             "description": pj.description})


def project_update(workspace: str, name: str, new_name: str | None = None,
                   description: str | None = None,
                   connection_id: str | None = None) -> dict[str, Any]:
    """Atualiza nome e/ou descrição de um project (o que vier None fica como está).

    **Use quando:** Renomear (religa os repositórios) ou descrever um project, sem mover item.
    **Retorna:** {id, workspace_id, name, description, items, subjects}.
    **Exemplo:** project_update(workspace="Polara", name="app", new_name="app-web")
    """
    svc = ProjectService(connection_id=connection_id)
    pj = svc.update(workspace, name, new_name, description)
    return _row(svc.rows(workspace), pj.id, {"id": pj.id, "name": pj.name,
                                             "description": pj.description})


def project_merge(workspace: str, source: str, target: str,
                  connection_id: str | None = None) -> dict[str, Any]:
    """Unifica dois projects do mesmo workspace: move os itens de `source` para `target`
    (subjects homônimos mesclados), religa os repositórios e apaga `source`.

    **Use quando:** Dois projects acabaram duplicados.
    **Retorna:** {merged_items, merged_subjects}.
    **Exemplo:** project_merge(workspace="Polara", source="app-old", target="app")
    """
    return ProjectService(connection_id=connection_id).merge(workspace, source, target)


def project_delete(workspace: str, name: str, confirm: bool = False,
                   connection_id: str | None = None) -> dict[str, Any]:
    """Remove um project com os itens dele. Destrutivo.

    **Use quando:** O usuário pediu para remover um project que não serve mais.
    **Retorna:** sem `confirm` → {status: "preview", would_delete: {workspace, project,
        items}} (nada muda); com `confirm=True` → {status: "deleted", workspace, project, items}.
    **Exemplo:** project_delete(workspace="Polara", name="Teste", confirm=True)
    **Erro comum:** passar `confirm=True` sem mostrar a prévia ao usuário.
    """
    ws = WorkspaceService(connection_id=connection_id).get(workspace)
    svc = ProjectService(connection_id=connection_id)
    pj = svc.get(ws.id, name)
    row = _row(svc.rows(ws.id), pj.id, {"items": 0})
    would = {"workspace": ws.name, "project": pj.name, "items": row["items"]}
    if not confirm:
        return {"status": "preview", "would_delete": would}
    svc.delete(ws.id, pj.id)
    return {"status": "deleted", **would}


def subject_list(workspace: str, project: str,
                 connection_id: str | None = None) -> list[dict[str, Any]]:
    """Lista os subjects de um project (subject = assunto opcional que agrupa itens).

    **Use quando:** Ver o que já existe antes de criar ou organizar.
    **Retorna:** [{id, name, description, scope, scope_explicit, items}] — `scope` é o que vale
        (herdado do project e do workspace se não explícito).
    **Exemplo:** subject_list(workspace="Polara", project="app")
    """
    return SubjectService(connection_id=connection_id).rows(workspace, project)


def subject_create(workspace: str, project: str, name: str, description: str | None = None,
                   connection_id: str | None = None) -> dict[str, Any]:
    """Cria um subject dentro de um project (o `item_save` com `subject` também cria).

    **Use quando:** Agrupar itens de um conceito/assunto (ex.: crédito privado).
    **Retorna:** {id, name, description, items}.
    **Exemplo:** subject_create(workspace="Polara", project="app", name="pagamentos")
    **Erro comum:** "Project não encontrado" — confira com project_list(workspace=...).
    """
    svc = SubjectService(connection_id=connection_id)
    sj = svc.create(workspace, project, name, description)
    return _row(svc.rows(workspace, project), sj.id,
                {"id": sj.id, "name": sj.name, "description": sj.description})


def subject_update(workspace: str, project: str, name: str, new_name: str | None = None,
                   description: str | None = None,
                   connection_id: str | None = None) -> dict[str, Any]:
    """Atualiza nome e/ou descrição de um subject (o que vier None fica como está).

    **Use quando:** Renomear (regrava os itens) ou descrever o assunto.
    **Retorna:** {id, name, description, items}.
    **Exemplo:** subject_update(workspace="Polara", project="app", name="pagto",
        new_name="pagamentos")
    """
    svc = SubjectService(connection_id=connection_id)
    sj = svc.update(workspace, project, name, new_name, description)
    return _row(svc.rows(workspace, project), sj.id,
                {"id": sj.id, "name": sj.name, "description": sj.description})


def subject_merge(workspace: str, project: str, source: str, target: str,
                  connection_id: str | None = None) -> dict[str, Any]:
    """Unifica dois subjects do mesmo project: move os itens de `source` para `target` e
    apaga `source`.

    **Use quando:** Dois subjects acabaram duplicados.
    **Retorna:** {merged_items}.
    **Exemplo:** subject_merge(workspace="Polara", project="app", source="pagto",
        target="pagamentos")
    """
    return SubjectService(connection_id=connection_id).merge(workspace, project, source, target)


def subject_delete(workspace: str, project: str, name: str, confirm: bool = False,
                   connection_id: str | None = None) -> dict[str, Any]:
    """Remove um subject. Nunca apaga item: os itens dele ficam sem subject (sobem para o
    project).

    **Use quando:** Um assunto não serve mais, mas os itens continuam valendo.
    **Retorna:** sem `confirm` → {status: "preview", would_delete: {subject,
        items_sem_assunto}}; com `confirm=True` → {status: "deleted", subject,
        items_sem_assunto}.
    **Exemplo:** subject_delete(workspace="Polara", project="app", name="pagamentos",
        confirm=True)
    """
    svc = SubjectService(connection_id=connection_id)
    sj = svc.get(workspace, project, name)
    row = _row(svc.rows(workspace, project), sj.id, {"items": 0})
    would = {"subject": sj.name, "items_sem_assunto": row["items"]}
    if not confirm:
        return {"status": "preview", "would_delete": would}
    svc.delete(workspace, project, sj.id)
    return {"status": "deleted", **would}


# --------------------------------------------------------------------------------------
# repo: link / list / unlink / sync
# --------------------------------------------------------------------------------------


def repo(
    action: str,
    repo: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
    confirm_new: bool = False,
    connection_id: str | None = None,
) -> Any:
    """Liga, lista ou desliga repositórios (remote do git ou caminho) de um workspace/project;
    sincroniza a pasta git da conexão.

    **Use quando:** Preparar um repositório pela primeira vez (`/plumb-setup` faz isso), auditar
        os vínculos, desfazer um, ou puxar o que mudou no remote da conexão (`action="sync"`).
    **Retorna:** link → {repo_key, workspace, project} ou, se o nome parecer com um
        workspace/project existente grafado diferente, {status: "candidate", candidate_match:
        {field, input, candidate}} (nada é criado); list → [{repo_key, workspace, project}];
        unlink → {status: "deleted", repo_key}; sync → {synced: bool}.
    **Exemplo:** repo(action="link", repo=".") · repo(action="list", workspace="Polara") ·
        repo(action="unlink", repo="github.com/org/antigo") · repo(action="sync")
    **Erro comum:** `candidate_match` na resposta — repita com o nome exato do existente ou
        com `confirm_new=True` para criar o novo.
    **Notas:** `repo` aceita caminho (qualquer pasta do repositório), URL do remote ou chave (o
        remote normalizado; sem remote, o caminho). Sem workspace: o de outro repositório do
        mesmo dono já ligado (senão o dono no remote; sem remote, `Pessoal`); sem project, o
        nome do repositório. Religar move o vínculo.
    """
    if action == "link":
        if not repo:
            raise ValidationError('link exige repo (ex.: repo(action="link", repo="."))')
        return RepoService(connection_id=connection_id).link(
            repo, workspace, project, confirm_new=confirm_new
        )
    if action == "list":
        return RepoService(connection_id=connection_id).list_links(workspace, project)
    if action == "unlink":
        if not repo:
            raise ValidationError('unlink exige repo (ex.: repo(action="unlink", repo="."))')
        svc = RepoService(connection_id=connection_id)
        key = svc.resolve(repo) or {}
        svc.unlink(repo)
        return {"status": "deleted", "repo_key": key.get("repo_key", repo)}
    if action == "sync":
        return {"synced": sync_connection(resolve_connection(connection_id))}
    raise ValidationError(f"action deve ser link, list, unlink ou sync (recebi {action!r})")


# --------------------------------------------------------------------------------------
# itens
# --------------------------------------------------------------------------------------


def item_search(
    query: str = "",
    queries: list[str] | None = None,
    repo: str | None = None,
    workspace: str | None = None,
    everywhere: bool = False,
    paths: list[str] | None = None,
    types: list[str] | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Busca explicada pela cadeia de alcance. Devolve resumos, nunca o `content` completo.

    **Use quando:** Procurar algo que pode já estar guardado (regra, decisão, como fazer) antes
        de agir ou de gravar; `paths` = os arquivos em que você vai mexer.
    **Retorna:** {results: [{id, key, type, title, summary, where, tags, score, matched_in,
        snippet, url}]} (com `paths`, também `excerpt`); com `queries` → {groups: [{query,
        results}]}; sem consulta, de um repositório ligado → o essencial em {groups: [{group,
        results}]} (seguranca, regras, contexto, trabalho). Pasta não ligada: só os do nível mais
        alto e `suggestion` com a chamada que liga.
    **Exemplo:** item_search(query="migração flyway", repo=".") ·
        item_search(queries=["estorno", "pix"], repo=".", paths=["src/payments/Charge.java"])
    **Erro comum:** filtro com valor fora da taxonomia — a mensagem lista os válidos; mais de 5
        `queries` — divida em chamadas.
    **Notas:** Alcance pela hierarquia: o item vale onde mora (workspace → project → subject) e
        abaixo; `where` diz onde ele mora, e quanto mais perto do seu project, maior o peso. Sem
        `repo`/`workspace`/`everywhere`, usa a pasta atual se ligada; `workspace=` busca o
        workspace inteiro; `everywhere=True`, tudo. Padrão esconde os com a tag `archived`.
        Filtros: types <<TYPES>>; tags (todas precisam bater). limit 1–100.
    """
    viewpoint: Viewpoint = None
    unlinked: str | None = None
    found = RepoService(connection_id=connection_id).resolve(repo or ".") if (
        repo or (not workspace and not everywhere)) else None
    if found:
        viewpoint = (found["workspace_id"], found["project_id"])
    elif repo:
        unlinked = repo  # pasta não ligada: como sem repo (só os globais + suggestion)
    out = ItemService(connection_id=connection_id).search(
        query=query, queries=queries, viewpoint=viewpoint, workspace=workspace,
        everywhere=everywhere, paths=paths, types=types, tags=tags, limit=limit,
    )
    if unlinked and "suggestion" in out:
        out["suggestion"] = SUGGESTION.replace('repo="."', f'repo="{unlinked}"')
    return out


def item_get(
    keys: list[str] | None = None,
    ids: list[str] | None = None,
    repo: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
    connection_id: str | None = None,
) -> list[dict[str, Any]]:
    """Lê itens completos (com `content` e `links`) por key e/ou id, até 20 de uma vez.

    **Use quando:** O resumo da busca ou do pacote não bastou.
    **Retorna:** Na ordem pedida (keys, depois ids): [{id, key, workspace, project, subject,
        where, type, title, summary, content, tags, links, created_at, updated_at, url}]; o
        que não se acha vem como {key|id, missing: true}, sem derrubar os outros. `links` inclui
        as ligações a outros itens ({item, rel}) e as referências externas ({url}|{path}).
    **Exemplo:** item_get(keys=["rule/money", "howto/deploy"], repo=".")
    **Erro comum:** key que vem `missing` sem `repo` — sem repositório só os do nível mais alto
        se resolvem pela key; passe `repo="."` (ou `workspace` + `project`, ou o `id`).
    **Notas:** A key é resolvida pela hierarquia do repositório (o project dele e o que ele
        enxerga acima). Ler conta como uso (`opened`).
    """
    return ItemService(connection_id=connection_id).get_many(
        keys=keys, ids=ids, viewpoint=_viewpoint(repo, connection_id),
        workspace=workspace, project=project,
    )


def item_save(
    items: list[dict[str, Any]], repo: str | None = None, connection_id: str | None = None
) -> list[dict[str, Any]]:
    """Grava até 20 itens numa publicação só (um erro desfaz o lote e aponta a entrada).

    **Use quando:** Guardar o que vale para depois — uma regra que o usuário enunciou, as
        decisões e aprendizados ao fechar uma mudança, a correção de um item.
    **Retorna:** [{index, id, key, action: created|updated|unchanged, warnings,
        similar?, url, has_value?, fill_url?}] — `url` é o link da UI local do item; `warnings`
        traz key fora do padrão e tag nova (com sugestão parecida); em modo PR, {index, id, key,
        status: pending_review|issue_opened, pr_url|issue_url}.
    **Modo, por entrada:** `key` → upsert no project (o preferido: regrava sem duplicar); `id` →
        atualiza só os campos informados (com `workspace`+`project` novos, move; só `subject`,
        troca o assunto); sem os dois → cria e devolve `similar` (títulos parecidos).
    **Campos aceitos:** <<FIELDS>>. Campo desconhecido é erro com a lista.
    **Valores:** type: <<TYPES>>. A nuance e o ciclo vão em `tags` (não em campos):
        ciclo <<LIFECYCLE>>; nuance (base, extensível) <<NUANCE>>. `links` liga a outro item
        ({"item": key, "rel": "depends_on"|"relates_to"}) ou a uma referência externa
        ({"url": "..."} | {"path": "src/**"}). key: `<tipo>/<nome>` em minúsculas com `-`.
    **Exemplo:** item_save(repo=".", items=[{"key": "rule/money", "type": "rule",
        "title": "Money em pagamentos", "summary": "Valores em Money, nunca double: "
        "arredondamento quebra a conciliação", "content": "...", "tags": ["pagamentos", "code"],
        "links": [{"path": "src/payments/**"}]}])
    **Exemplo (arquivar):** item_save(repo=".", items=[{"key": "rule/x", "tags": ["archived"]}])
    **Segredo:** {"key": "secret/npm-token", "type": "secret", "title": "Token do npm",
        "summary": "publicar no npm"} — sem valor (é recusado); passe ao usuário o `fill_url`
        da resposta (ele preenche na UI local). Usar: `knowledge-mcp run --env
        NPM_TOKEN=secret/npm-token -- <comando>`.
    **Erro comum:** sem `repo` e sem `workspace`+`project` na entrada → passe `repo="."`;
        repositório não ligado → `repo(action="link", repo=".")`; conteúdo com cara de segredo
        é recusado.
    """
    default = None
    if repo:
        link = _link(repo, connection_id)
        default = (link["workspace"], link["project"])
    return ItemService(connection_id=connection_id).save(items, default_location=default)


_fill(
    item_save,
    FIELDS=_codes(model.ITEM_FIELDS + model.LOCATION_FIELDS),
    TYPES=_codes(model.TYPES),
    LIFECYCLE=_codes(model.LIFECYCLE_TAGS),
    NUANCE=_codes(model.NUANCE_TAGS),
)
_fill(
    item_search,
    TYPES=", ".join(model.TYPES),
    LINK_RELATIONS=", ".join(model.LINK_RELATIONS),
)


def item_delete(
    keys: list[str] | None = None,
    ids: list[str] | None = None,
    repo: str | None = None,
    confirm: bool = False,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Limpeza em três passos: candidatos, prévia e remoção. Destrutivo só com `confirm=True`.

    **Use quando:** Sem keys, para achar o que pode sair; com keys, para remover um item errado
        sem histórico a preservar (para aposentar mantendo-o, `status: "archived"` no item_save).
    **Retorna:** sem keys/ids → {candidates: [{key, id, reason}]} (reason: expired,
        archived_90d, stale_review_14d, unused, irrelevant; nunca itens `origin=user`); com
        keys/ids e sem `confirm` → {status: "preview", items: [{id, key, type, title, where,
        relations_in}], missing?}; com `confirm=True` → {status: "deleted", ids, missing?}
        (as relações que apontam para o item saem no mesmo commit).
    **Exemplo:** item_delete(repo=".") · item_delete(keys=["rule/velha"], repo=".",
        confirm=True)
    **Erro comum:** passar `confirm=True` sem mostrar a prévia ao usuário.
    """
    return ItemService(connection_id=connection_id).delete(
        keys=keys, ids=ids, viewpoint=_viewpoint(repo, connection_id), confirm=confirm
    )


def item_graph(
    keys: list[str],
    repo: str | None = None,
    depth: int = 1,
    limit: int = 20,
    relation_types: list[str] | None = None,
    types: list[str] | None = None,
    direction: str = "both",
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Vizinhança de itens pelo grafo de links item↔item (só o que o repositório enxerga).

    **Use quando:** Entender o que depende de um item ou se relaciona com ele, antes de mudá-lo.
    **Retorna:** {nodes: [{key, id, type, title, summary, hop}], edges:
        [{from, type, to}], truncated, total_by_hop} — as `keys` vêm com `hop: 0`.
    **Exemplo:** item_graph(keys=["rule/money"], repo=".", depth=2,
        relation_types=["depends_on"])
    **Erro comum:** mais de 5 keys, depth fora de 1–3 ou limit acima de 100 — a mensagem diz o
        limite; key fora do alcance → confira com item_search ou passe o id.
    **Notas:** direction: both, out (o que o item aponta) ou in (o que aponta para ele).
    """
    return GraphService(connection_id=connection_id).graph(
        keys, viewpoint=_viewpoint(repo, connection_id), depth=depth, limit=limit,
        relation_types=relation_types, types=types, direction=direction,
    )


# --------------------------------------------------------------------------------------
# relações
# --------------------------------------------------------------------------------------


def relation_create(
    items: list[dict[str, Any]], repo: str | None = None, connection_id: str | None = None
) -> list[dict[str, Any]]:
    """Cria relações entre itens existentes, em lote atômico (até 20).

    **Use quando:** Ligar itens: um howto que depende de uma regra, dois itens que se relacionam.
    **Retorna:** [{index, source, type, target, action: created|unchanged}].
    **Exemplo:** relation_create(repo=".", items=[{"source": "howto/deploy-ci",
        "type": "depends_on", "target": "rule/deploy"}])
    **Erro comum:** tipo inválido — a mensagem lista os válidos (<<RELATIONS>>); key fora do
        alcance — passe `repo="."` ou o id.
    **Notas:** source/target são key ou id, resolvidos pela cadeia de alcance do repositório. A
        relação fica no arquivo do item de origem.
    """
    return RelationService(connection_id=connection_id).create(
        items, viewpoint=_viewpoint(repo, connection_id)
    )


def relation_delete(
    items: list[dict[str, Any]], repo: str | None = None, connection_id: str | None = None
) -> list[dict[str, Any]]:
    """Remove relações entre itens, em lote atômico (até 20).

    **Use quando:** Uma relação foi criada por engano ou deixou de valer.
    **Retorna:** [{index, source, type, target, action: deleted|missing}].
    **Exemplo:** relation_delete(repo=".", items=[{"source": "rule/a", "type": "relates_to",
        "target": "rule/b"}])
    """
    return RelationService(connection_id=connection_id).delete(
        items, viewpoint=_viewpoint(repo, connection_id)
    )


_fill(relation_create, RELATIONS=", ".join(model.LINK_RELATIONS))


# --------------------------------------------------------------------------------------
# tags
# --------------------------------------------------------------------------------------


def tag_list(connection_id: str | None = None) -> list[dict[str, Any]]:
    """Lista as tags (vocabulário da conexão), com quantos itens usam cada uma.

    **Use quando:** Reaproveitar uma tag existente antes de inventar uma variação.
    **Retorna:** [{name, count}] por nome (inclui as sem item, `count: 0`).
    **Exemplo:** tag_list()
    """
    return TagService(connection_id=connection_id).list()


def tag_create(names: list[str], connection_id: str | None = None) -> dict[str, Any]:
    """Registra tags no vocabulário (kebab-case minúsculo). O item_save também cria, com aviso.

    **Use quando:** Preparar o vocabulário de um assunto antes de gravar itens.
    **Retorna:** {created, existing} (nomes normalizados).
    **Exemplo:** tag_create(names=["lgpd", "pix"])
    """
    return TagService(connection_id=connection_id).create(names)


def tag_update(name: str, new_name: str, connection_id: str | None = None) -> dict[str, Any]:
    """Renomeia uma tag em todos os itens e no vocabulário, num commit; se `new_name` já existe,
    mescla as duas.

    **Use quando:** Corrigir a grafia de uma tag ou unificar duas.
    **Retorna:** {renamed: itens regravados, merged: bool}.
    **Exemplo:** tag_update(name="pix", new_name="pagamento-pix")
    **Erro comum:** "Tag não encontrada" — a mensagem lista as existentes.
    """
    return TagService(connection_id=connection_id).update(name, new_name)


def tag_delete(names: list[str], confirm: bool = False,
               connection_id: str | None = None) -> dict[str, Any]:
    """Remove tags dos itens e do vocabulário. Sem `confirm`, só a prévia.

    **Use quando:** Uma tag não faz mais sentido.
    **Retorna:** sem `confirm` → {status: "preview", tags: [{name, items}]}; com `confirm=True`
        → {status: "deleted", tags: [{name, items}]}.
    **Exemplo:** tag_delete(names=["lgpd"]) e, confirmado, tag_delete(names=["lgpd"],
        confirm=True)
    **Erro comum:** "Tag não encontrada" — a mensagem lista as existentes (tag_list).
    """
    return TagService(connection_id=connection_id).delete(names, confirm=confirm)


# --------------------------------------------------------------------------------------
# connection e health_check
# --------------------------------------------------------------------------------------


def _connection_view(conn: Any) -> dict[str, Any]:
    return {
        "id": conn.id,
        "name": conn.name,
        "path": getattr(conn, "path", None),
        "remote_url": getattr(conn, "remote_url", None),
        "review_mode": getattr(conn, "review_mode", "direct"),
        "enabled": bool(conn.is_active),
        "is_default": bool(getattr(conn, "is_default", False)),
    }


def connection_create(
    name: str, path: str, remote_url: str | None = None, review_mode: str = "direct"
) -> dict[str, Any]:
    """Cria uma conexão: uma pasta local (repositório git) onde os itens viram arquivos
    Markdown.

    **Use quando:** Começar a guardar conhecimento numa pasta escolhida pelo usuário (com ou
        sem GitHub). Sem conexão nenhuma outra ferramenta funciona.
    **Retorna:** {id, name, path, remote_url, review_mode, enabled, is_default}.
    **Exemplo:** connection_create(name="Polara", path="/home/user/polara-knowledge")
    **Erro comum:** path relativo ou dentro do home de dados do Knowledge OS — use uma pasta
        absoluta fora dele.
    **Notas:** Se a pasta já for um repositório git, é usada como está; senão vira um (`git
        init`, preservando o conteúdo). Com `remote_url`, `path` é o destino do clone.
        `review_mode="pr"` publica por Pull Request. A primeira conexão vira a padrão.
    """
    conn = ConnectionService().create(name, path, remote_url=remote_url, review_mode=review_mode)
    return _connection_view(conn)


def connection_list() -> list[dict[str, Any]]:
    """Lista as conexões cadastradas (a padrão marcada com `is_default`).

    **Use quando:** Ver as conexões ou achar o id para `connection_id`/`connection_delete`.
    **Retorna:** [{id, name, path, remote_url, review_mode, enabled, is_default}].
    **Exemplo:** connection_list()
    """
    return [_connection_view(c) for c in ConnectionService().list()]


def connection_delete(id: str) -> dict[str, Any]:
    """Remove uma conexão do cadastro. Não apaga a pasta: são dados do usuário.

    **Use quando:** Parar de usar uma conexão sem apagar os dados dela.
    **Retorna:** {status: deleted|not_found, id}.
    **Exemplo:** connection_delete(id="...")
    """
    deleted = ConnectionService().delete(id)
    return {"status": "deleted" if deleted else "not_found", "id": id}


def health_check() -> dict[str, Any]:
    """Saúde do servidor e das conexões (nada é criado).

    **Use quando:** Diagnosticar uma falha, confirmar que o servidor está de pé ou achar os
        arquivos `.md` que a leitura ignorou.
    **Retorna:** {status: ok|error, version, connections: [{id, name, path, ok, parse_errors:
        [{path, error}]}], gh_authenticated, message?} — `ok` só com ao menos uma conexão e
        todas com a pasta git acessível; `message` diz o que fazer quando `error`.
    **Exemplo:** health_check()
    **Erro comum:** `status: error` sem conexões — crie uma com connection_create(name, path).
    **Notas:** `parse_errors` lista os arquivos com frontmatter inválido (ou id duplicado): eles
        não aparecem em busca nenhuma até serem corrigidos. `gh_authenticated` (`gh auth
        status`) só importa para conexões com `remote_url` e `review_mode="pr"`.
    """
    from knowledge_os import __version__
    from knowledge_os.services import gh_cli

    base = {"version": __version__, "gh_authenticated": gh_cli.is_authenticated()}
    try:
        connections = ConnectionService().health()
    except (ConfigError, ValidationError) as exc:
        return {"status": "error", "connections": [], "message": str(exc), **base}
    out: dict[str, Any] = {"connections": connections, **base}
    broken = [c["name"] for c in connections if not c["ok"]]
    if not connections:
        out.update(status="error", message=NO_CONNECTION_MESSAGE)
    elif broken:
        out.update(status="error", message="Pasta inacessível ou sem repositório git: "
                   + ", ".join(broken) + ". Confira o path em connection_list().")
    else:
        out["status"] = "ok"
    return {"status": out.pop("status"), **out}


TOOLS: tuple[Callable[..., Any], ...] = (
    workspace_list, workspace_create, workspace_update, workspace_merge, workspace_delete,
    project_list, project_create, project_update, project_merge, project_delete,
    subject_list, subject_create, subject_update, subject_merge, subject_delete,
    repo,
    item_search, item_get, item_save, item_delete, item_graph,
    relation_create, relation_delete,
    tag_list, tag_create, tag_update, tag_delete,
    connection_create, connection_list, connection_delete,
    health_check,
)


def register(mcp: FastMCP) -> None:
    """Registra as 31 ferramentas no servidor."""
    for fn in TOOLS:
        mcp.tool()(fn)
