"""Ferramentas MCP do Knowledge OS: uma função por operação (sem `action=` agrupando).

Exceção: `repo` ainda agrupa link/list/unlink/sync por `action=` — é usado por um volume
grande de automação existente (hook de sessão, `/plumb-setup`, fila offline) e manter o
nome/assinatura evita uma quebra de compatibilidade ampla demais para esta rodada.
"""

from typing import Any

from fastmcp import FastMCP
from sqlalchemy import func, select

from knowledge_os.config import CATALOG_ID, ConfigManager
from knowledge_os.db.models import DEFAULT_CONNECTION_ID, Item, Project, Workspace
from knowledge_os.db.session import connection_id_of, default_connection_id, get_engine, get_session
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.schemas.item_schemas import ItemResponse, ItemSearchRequest, ItemSearchResult
from knowledge_os.schemas.relation_schemas import RelationListResponse
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.context_service import ContextService
from knowledge_os.services.git_repo_service import GitRepoService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.label_service import LabelService
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.relation_service import RELATION_TYPES, RelationService
from knowledge_os.services.repo_service import RepoService
from knowledge_os.services.secret_service import SecretService
from knowledge_os.services.subject_service import SubjectService
from knowledge_os.services.tag_service import TagService
from knowledge_os.services.workspace_service import WorkspaceService

MAX_GET = 20


# --------------------------------------------------------------------------------------
# workspace / project / subject: uma função por operação (list/create/rename/merge/delete)
# --------------------------------------------------------------------------------------


def _location_tree(workspace: str | None, connection_id: str | None) -> list[dict[str, Any]]:
    """Árvore workspaces → projects com a contagem de itens (base de workspace/project list)."""
    engine = get_engine(connection_id) if connection_id else get_engine()
    cid = connection_id or connection_id_of(engine) or "default"
    session = get_session(engine)
    try:
        query = select(Workspace).where(Workspace.connection_id == cid).order_by(Workspace.name)
        if workspace:
            query = query.where((Workspace.name == workspace) | (Workspace.id == workspace))
        workspaces = list(session.scalars(query))
        counts = dict(
            session.execute(select(Item.project_id, func.count()).group_by(Item.project_id)).all()
        )
        out = []
        for ws in workspaces:
            projects = list(
                session.scalars(
                    select(Project).where(Project.workspace_id == ws.id).order_by(Project.name)
                )
            )
            rows = [{"name": d.name, "items": counts.get(d.id, 0)} for d in projects]
            out.append(
                {
                    "workspace": ws.name,
                    "description": ws.description,
                    "items": sum(r["items"] for r in rows),
                    "projects": rows,
                }
            )
    finally:
        session.close()
    if workspace and not out:
        raise NotFoundError(f"Workspace não encontrado: {workspace}")
    return out


def workspace_list(name: str | None = None, connection_id: str | None = None) -> Any:
    """Lista workspaces (contexto de trabalho: empresa, cliente, Pessoal, Global).

    **Use quando:** Ver o que já existe antes de criar ou organizar.
    **Retorna:** [{name, description, projects, items}].
    **Exemplo:** workspace_list()
    """
    rows = _location_tree(name, connection_id)
    return [
        {
            "name": r["workspace"],
            "description": r["description"],
            "projects": len(r["projects"]),
            "items": r["items"],
        }
        for r in rows
    ]


def workspace_create(
    name: str, description: str | None = None, connection_id: str | None = None
) -> Any:
    """Cria um workspace (contexto de trabalho: empresa, cliente, Pessoal, Global).

    **Use quando:** Criar um novo contexto de trabalho.
    **Retorna:** {id, name, description}.
    **Exemplo:** workspace_create(name="Polara")
    """
    row = WorkspaceService(connection_id=connection_id).create(name, description)
    return {"id": row.id, "name": row.name, "description": row.description}


def workspace_rename(name: str, new_name: str, connection_id: str | None = None) -> Any:
    """Renomeia um workspace.

    **Use quando:** Corrigir ou atualizar o nome de um workspace.
    **Retorna:** {id, name}.
    **Exemplo:** workspace_rename(name="polara", new_name="Polara")
    """
    row = WorkspaceService(connection_id=connection_id).rename(name, new_name)
    return {"id": row.id, "name": row.name}


def workspace_merge(source: str, target: str, connection_id: str | None = None) -> Any:
    """Unifica dois workspaces: move os projects de `source` para `target` (projects
    homônimos são mesclados por nome, não duplicados) e apaga `source`.

    **Use quando:** Unificar dois workspaces que acabaram duplicados.
    **Retorna:** {merged_projects, renamed_collisions}.
    **Exemplo:** workspace_merge(source="Polara Antiga", target="Polara")
    """
    return WorkspaceService(connection_id=connection_id).merge(source, target)


def workspace_delete(name: str, confirm: bool = False, connection_id: str | None = None) -> Any:
    """Remove um workspace de vez.

    **Use quando:** Remover um workspace que não serve mais.
    **Retorna:** sem `confirm` → {status: preview, would_delete}; com `confirm=True` →
        {status: deleted, ...}.
    **Exemplo:** workspace_delete(name="Teste", confirm=True)
    **Notas:** Sem `confirm`, só mostra o preview; chame de novo com `confirm=True` para
        apagar de vez.
    """
    svc = WorkspaceService(connection_id=connection_id)
    if not name:
        raise ValidationError("delete exige name")
    preview = _location_tree(name, connection_id)[0]
    would = {"workspace": name, "projects": len(preview["projects"]), "items": preview["items"]}
    if not confirm:
        return {"status": "preview", "would_delete": would}
    svc.delete(name)
    return {"status": "deleted", **would}


def project_list(workspace: str, connection_id: str | None = None) -> Any:
    """Lista os projects de um workspace (project = o repositório dentro do workspace;
    `Geral` guarda o que vale para todos).

    **Use quando:** Ver o que já existe antes de criar ou organizar.
    **Retorna:** [{name, items}].
    **Exemplo:** project_list(workspace="Polara")
    """
    return _location_tree(workspace, connection_id)[0]["projects"]


def project_create(
    workspace: str, name: str, description: str | None = None, connection_id: str | None = None
) -> Any:
    """Cria um project dentro de um workspace.

    **Use quando:** Organizar um novo repositório dentro do workspace.
    **Retorna:** {id, name, description}.
    **Exemplo:** project_create(workspace="Polara", name="projpro")
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    row = ProjectService(connection_id=connection_id).create(ws_id, name, description)
    return {"id": row.id, "name": row.name, "description": row.description}


def project_rename(
    workspace: str, name: str, new_name: str, connection_id: str | None = None
) -> Any:
    """Renomeia um project.

    **Use quando:** Corrigir ou atualizar o nome de um project.
    **Retorna:** {id, name}.
    **Exemplo:** project_rename(workspace="Polara", name="projpro", new_name="ProjPro")
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    row = ProjectService(connection_id=connection_id).rename(ws_id, name, new_name)
    return {"id": row.id, "name": row.name}


def project_merge(
    workspace: str, source: str, target: str, connection_id: str | None = None
) -> Any:
    """Unifica dois projects do mesmo workspace: move os items de `source` para `target`
    (subjects homônimos mesclados por nome) e apaga `source`.

    **Use quando:** Unificar dois projects que acabaram duplicados.
    **Retorna:** {merged_items, merged_subjects}.
    **Exemplo:** project_merge(workspace="Polara", source="projpro-old", target="projpro")
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    return ProjectService(connection_id=connection_id).merge(ws_id, source, target)


def project_delete(
    workspace: str, name: str, confirm: bool = False, connection_id: str | None = None
) -> Any:
    """Remove um project de vez.

    **Use quando:** Remover um project que não serve mais.
    **Retorna:** sem `confirm` → {status: preview, would_delete}; com `confirm=True` →
        {status: deleted, ...}.
    **Exemplo:** project_delete(workspace="Polara", name="Teste", confirm=True)
    """
    if not name:
        raise ValidationError("delete exige name")
    preview = _location_tree(workspace, connection_id)[0]
    match = [d for d in preview["projects"] if d["name"] == name]
    if not match:
        raise NotFoundError(f"Project não encontrado: {name}")
    would = {"project": name, "items": match[0]["items"]}
    if not confirm:
        return {"status": "preview", "would_delete": would}
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    ProjectService(connection_id=connection_id).delete(ws_id, name)
    return {"status": "deleted", **would}


def subject_list(workspace: str, project: str, connection_id: str | None = None) -> Any:
    """Lista os subjects de um project (subject = assunto opcional que agrupa items).

    **Use quando:** Ver o que já existe antes de criar ou organizar.
    **Retorna:** [{name, items}].
    **Exemplo:** subject_list(workspace="Polara", project="app")
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    pj_id = ProjectService(connection_id=connection_id).get(ws_id, project).id
    svc = SubjectService(connection_id=connection_id)
    session = get_session(get_engine(connection_id) if connection_id else get_engine())
    try:
        counts = dict(
            session.execute(
                select(Item.subject_id, func.count())
                .where(Item.project_id == pj_id)
                .group_by(Item.subject_id)
            ).all()
        )
    finally:
        session.close()
    return [{"name": s.name, "items": counts.get(s.id, 0)} for s in svc.list(pj_id)]


def subject_create(
    workspace: str,
    project: str,
    name: str,
    description: str | None = None,
    connection_id: str | None = None,
) -> Any:
    """Cria um subject dentro de um project.

    **Use quando:** Agrupar items relacionados dentro de um project.
    **Retorna:** {id, name, description}.
    **Exemplo:** subject_create(workspace="Polara", project="app", name="pagamentos")
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    pj_id = ProjectService(connection_id=connection_id).get(ws_id, project).id
    row = SubjectService(connection_id=connection_id).create(pj_id, name, description)
    return {"id": row.id, "name": row.name, "description": row.description}


def subject_rename(
    workspace: str, project: str, name: str, new_name: str, connection_id: str | None = None
) -> Any:
    """Renomeia um subject.

    **Use quando:** Corrigir ou atualizar o nome de um subject.
    **Retorna:** {id, name}.
    **Exemplo:** subject_rename(workspace="Polara", project="app", name="pagamentos",
        new_name="Pagamentos")
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    pj_id = ProjectService(connection_id=connection_id).get(ws_id, project).id
    row = SubjectService(connection_id=connection_id).rename(pj_id, name, new_name)
    return {"id": row.id, "name": row.name}


def subject_merge(
    workspace: str, project: str, source: str, target: str, connection_id: str | None = None
) -> Any:
    """Unifica dois subjects do mesmo project: move os items de `source` para `target` e
    apaga `source`.

    **Use quando:** Unificar dois subjects que acabaram duplicados.
    **Retorna:** {merged_items}.
    **Exemplo:** subject_merge(workspace="Polara", project="app", source="pagto",
        target="pagamentos")
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    pj_id = ProjectService(connection_id=connection_id).get(ws_id, project).id
    return SubjectService(connection_id=connection_id).merge(pj_id, source, target)


def subject_delete(
    workspace: str,
    project: str,
    name: str,
    confirm: bool = False,
    connection_id: str | None = None,
) -> Any:
    """Remove um subject. Nunca apaga item, só desvincula (`subject_id = None`).

    **Use quando:** Um subject não serve mais, mas os items continuam valendo.
    **Retorna:** sem `confirm` → {status: preview, would_delete: {items_sem_assunto}}; com
        `confirm=True` → {status: deleted}.
    **Exemplo:** subject_delete(workspace="Polara", project="app", name="pagamentos",
        confirm=True)
    """
    if not name:
        raise ValidationError("delete exige name")
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    pj_id = ProjectService(connection_id=connection_id).get(ws_id, project).id
    svc = SubjectService(connection_id=connection_id)
    sj = svc.get(pj_id, name)
    session = get_session(get_engine(connection_id) if connection_id else get_engine())
    try:
        orphaned = session.scalar(
            select(func.count()).select_from(Item).where(Item.subject_id == sj.id)
        )
    finally:
        session.close()
    if not confirm:
        return {
            "status": "preview",
            "would_delete": {"subject": name, "items_sem_assunto": orphaned},
        }
    svc.delete(pj_id, name)
    return {"status": "deleted", "subject": name, "items_sem_assunto": orphaned}


# --------------------------------------------------------------------------------------
# repo: link / list / unlink / sync — continua por action= (ver docstring do módulo)
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
    sincroniza o repositório git da connection.

    **Use quando:** Configurar um projeto pela primeira vez (`/plumb-setup` faz isso),
        auditar o que já está ligado, desfazer um vínculo, ou puxar manualmente o que
        mudou no repositório da connection (`action="sync"`).
    **Retorna:** link → {repo_key, workspace, project} ou, se o nome candidato parecer com
        um workspace/project já existente mas grafado diferente, {status: "candidate",
        candidate_match: {field, input, candidate}} (sem criar nada); list →
        [{repo_key, workspace, project}]; unlink → {status: deleted, repo_key}; sync →
        {synced: bool} (true se havia algo novo e foi puxado).
    **Exemplo:** repo(action="link", repo=".") · repo(action="list", workspace="Polara") ·
        repo(action="unlink", repo="github.com/org/antigo") · repo(action="sync")
    **Notas:** repo aceita caminho (qualquer pasta do repo), URL do remote ou chave; a
        chave é o remote do git normalizado (ou o caminho, sem remote). workspace/project são
        criados se não existirem, a menos que o candidate_match apareça: nesse caso, repita
        a chamada com confirm_new=True para confirmar a criação (ou passe o nome exato do
        existente). Workspace e project seguem: sem workspace, o de outro repo do mesmo dono
        já ligado (senão o nome do dono no remote; sem remote, `Pessoal`); sem project, o
        nome do repositório. Religar move o vínculo. `sync` é por connection (não por
        repo/workspace/project): no catálogo (sem connection configurada) sempre devolve
        {synced: false}, não há o que sincronizar.
    """
    if action == "link":
        if not repo:
            raise ValidationError("link exige repo")
        return RepoService(connection_id=connection_id).link(
            repo, workspace, project, confirm_new=confirm_new
        )
    if action == "list":
        return RepoService(connection_id=connection_id).list_links(workspace, project)
    if action == "unlink":
        if not repo:
            raise ValidationError("unlink exige repo")
        svc = RepoService(connection_id=connection_id)
        key = svc.resolve(repo) or {}
        svc.unlink(repo)
        return {"status": "deleted", "repo_key": key.get("repo_key", repo)}
    if action == "sync":
        cid = connection_id or default_connection_id()
        if cid == CATALOG_ID:
            return {"synced": False}
        conn = ConfigManager.load_or_create().get_connection(cid)
        git = GitRepoService(conn.clone_path(), conn.remote_url, conn.review_mode)
        git.ensure_clone()
        return {"synced": git.sync()}
    raise ValidationError("action deve ser link, list, unlink ou sync")


# --------------------------------------------------------------------------------------
# context_get / item_search / item_get / item_save
# --------------------------------------------------------------------------------------


def context_get(
    repo: str,
    paths: list[str] | None = None,
    query: str | None = None,
    budget_tokens: int = 1500,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Pacote de contexto do projeto: regras, contexto, decisões, padrões, procedimentos.

    **Use quando:** Começar num projeto (se o hook não injetou) ou ao passar a mexer em outra
        área: `paths` traz as regras com escopo daqueles arquivos; `query`, itens relacionados.
    **Retorna:** {linked, repo_key, workspace, project, markdown, included, omitted, sensitive}.
    **Exemplo:** context_get(repo=".", paths=["src/payments/Charge.java"], query="estorno")
    **Notas:** Dentro de `budget_tokens`. Itens que casam com `paths` ou `query` vêm em foco, com o
        começo do content (dispensa item_get); o resto, só título, resumo e key. `sensitive` é true
        se `paths` toca uma área marcada com a keyword "sensivel". Inclui o project do projeto,
        `Geral` do workspace e `Global/Geral`. Sem substituídos, obsoletos nem ephemeral.
    """
    return ContextService(connection_id=connection_id).build(repo, paths, query, budget_tokens)


def item_search(
    query: str = "",
    repo: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
    subject: str | None = None,
    types: list[str] | None = None,
    memory_classes: list[str] | None = None,
    limit: int = 10,
    include_inactive: bool = False,
    everywhere: bool = False,
    connection_id: str | None = None,
) -> list[dict[str, Any]]:
    """Busca por texto. Devolve resumos, nunca o conteúdo completo.

    **Use quando:** Procurar algo que pode já estar guardado (decisão, gotcha, procedimento).
    **Retorna:** [{id, key, type, memory_class, project, subject, title, summary, score, uses}].
    **Exemplo:** item_search(query="migração flyway", limit=5)
    **Notas:** Sem repo/workspace, busca no projeto da pasta atual (se ligado) — não vaza para
        outros projetos; `everywhere=True` busca em todos. Relevância primeiro; acentos e plurais
        não atrapalham. include_inactive traz substituídos, obsoletos e ephemeral vencidos.
        `subject` filtra pelo assunto (nome ou id) dentro do project; exige project resolvido.
    """
    svc = ItemService(connection_id=connection_id)
    workspace_id = project_id = subject_id = None
    if not repo and not workspace and not everywhere:
        repo = "." if RepoService(connection_id=connection_id).resolve(".") else None
    if repo:
        workspace_id = RepoService(connection_id=connection_id).require(repo)["workspace_id"]
    elif workspace:
        workspace_id = svc.resolve_workspace_id(workspace)
    if project:
        if workspace_id is None:
            raise ValidationError("project exige repo ou workspace")
        project_id = svc.resolve_project_id(workspace_id, project)
    if subject:
        if project_id is None:
            raise ValidationError("subject exige project")
        subject_id = svc.resolve_subject_id(project_id, subject)
    req = ItemSearchRequest(
        workspace_id=workspace_id,
        project_id=project_id,
        subject_id=subject_id,
        query=query,
        types=types,
        memory_classes=memory_classes,
        limit=limit,
    )
    rows = svc.search(
        req.workspace_id,
        req.project_id,
        req.query,
        req.subject_id,
        req.types,
        req.memory_classes,
        req.limit,
        include_inactive=include_inactive,
    )
    return [ItemSearchResult(**r).model_dump() for r in rows]


def item_get(
    ids: list[str] | None = None,
    keys: list[str] | None = None,
    repo: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
    connection_id: str | None = None,
) -> list[dict[str, Any]]:
    """Lê itens completos (content, tags, relações) por id e/ou key, vários de uma vez.

    **Use quando:** O resumo da busca ou do contexto não bastou.
    **Retorna:** Lista de itens completos, na ordem pedida; o que não existe vem como
        {key|id, missing: true}, sem derrubar os outros.
    **Exemplo:** item_get(keys=["regra/money", "proc/deploy"], repo=".")
    **Notas:** keys exigem repo (o project ligado) ou workspace e project. Até 20 por chamada.
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
        if repo:
            project_id = RepoService(connection_id=connection_id).require(repo)["project_id"]
        elif workspace and project:
            project_id = svc.resolve_project_id(svc.resolve_workspace_id(workspace), project)
        else:
            raise ValidationError("keys exigem repo ou workspace e project")
        items += [fetch(lambda k=k: svc.get_by_key(project_id, k), {"key": k}) for k in keys]
    svc.track_use([i.id for i in items if not isinstance(i, dict)])
    out: list[dict[str, Any]] = []
    relations = RelationService(connection_id=connection_id)
    for item in items:
        if isinstance(item, dict):
            out.append(item)
            continue
        data = ItemResponse.from_item(item).model_dump(mode="json")
        data["relations"] = RelationListResponse.model_validate(
            relations.list(item.id), from_attributes=True
        ).model_dump(mode="json")
        out.append(data)
    return out


def item_save(
    items: list[dict[str, Any]], repo: str | None = None, connection_id: str | None = None
) -> list[dict[str, Any]]:
    """Grava itens (criar, atualizar, upsert, renovar, relacionar) numa transação.

    **Use quando:** Guardar o que vale para depois — uma regra que o usuário enunciou, as
        decisões e aprendizados ao fechar uma mudança, uma correção de um item.
    **Retorna:** [{index, id, key, action: created|updated|unchanged, similar?, relations?}].
    **Modo, por entrada:** com `key` → upsert no project (não duplica; o preferido); com `id` →
        atualiza o item; sem os dois → cria e devolve `similar` (títulos parecidos já guardados).
        Com `id` e também `workspace`+`project` na mesma entrada → *move* o item para esse
        workspace/project (criados se não existirem); o `subject`, se vier, é resolvido/criado
        no project novo, senão o subject do item é zerado. Com `id` e só `subject` (sem
        workspace/project) → move o item para esse subject dentro do project atual. Em qualquer
        caso de `id`, id, created_at, access_count, tags, labels e relations do item
        não mudam — só as FKs de localização.
    **Exemplo (upsert):** item_save(repo=".", items=[{"key": "regra/money", "type": "rule",
        "title": "Money em pagamentos", "summary": "Valores em Money, nunca double",
        "content": "...", "scope_paths": ["src/payments/**"], "source": "PAY-142"}])
    **Exemplo (aposentar):** item_save(repo=".", items=[{"key": "regra/x",
        "status": "deprecated"}])
    **Exemplo (substituir):** item_save(repo=".", items=[{"key": "proc/deploy-v2", ...,
        "relations": [{"type": "supersedes", "target": "proc/deploy"}]}])
    **Campos:** type (rule, insight, procedure, pattern, knowledge, context, artifact, spec),
        title, summary, content, keywords, source, scope_paths, status (active, done,
        superseded, deprecated), memory_class "ephemeral" + ttl_days só para nota temporária
        (sem aprovação: o resto já vale), tags, labels, relations
        [{type: related_to|depends_on|implements|references|supersedes|derived_from, target: id
        ou key}], workspace/project (sem eles vale o project ligado a `repo`), subject (nome do
        assunto dentro do project — agrupador opcional, criado se não existir).
    **Segredo:** {"key": "segredo/npm-token", "type": "secret", "title": "Token do npm",
        "summary": "publicar no npm"} — sem valor (é recusado); a resposta traz `fill_url`:
        passe ao usuário para ele preencher na UI local. Usar: `knowledge-mcp run --env
        NPM_TOKEN=segredo/npm-token -- <comando>`.
    **Notas:** Um erro desfaz o lote e aponta a entrada. Conteúdo com cara de segredo é recusado.
        Numa connection com repositório git (não o catálogo), todo item não secreto também é
        publicado nesse repositório. Em `review_mode="direct"` (padrão), publica e atualiza o
        índice na mesma chamada — o retorno é o de sempre. Em `review_mode="pr"`, abre (ou
        atualiza) um Pull Request com o lote inteiro e devolve, por entrada,
        `{status: "pending_review", pr_url}` (ou `{status: "issue_opened", issue_url}` sem
        permissão de push) em vez de `{action, id, ...}` — o índice só reflete a mudança
        depois que o PR for mergeado e `repo(action="sync")` (ou o hook de sessão) sincronizar.
    """
    default = None
    if repo:
        link = RepoService(connection_id=connection_id).require(repo)
        default = (link["workspace_id"], link["project_id"])
    results = ItemService(connection_id=connection_id).save(items, default_location=default)
    secrets = SecretService(connection_id=connection_id).describe([r["id"] for r in results])
    return [{**r, **secrets.get(r["id"], {})} for r in results]


# --------------------------------------------------------------------------------------
# item_delete / relation_create / relation_delete
# --------------------------------------------------------------------------------------


def item_delete(item_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Remove um item de vez (com tags e relações). Destrutivo.

    **Use quando:** O item está errado e não há histórico a preservar.
    **Retorna:** {status: deleted, id} ou, se a connection usa modo `pr`, {status:
        pending_review, pr_url, id} (ou {status: issue_opened, issue_url, id}) — a
        remoção fica pendente de revisão e só sai do índice depois do PR mergeado e
        um `repo(action="sync")`.
    **Exemplo:** item_delete(item_id="...")
    **Notas:** Para aposentar mantendo o histórico, prefira item_save com status=deprecated ou
        uma relação supersedes.
    """
    return ItemService(connection_id=connection_id).delete_published(item_id)


def relation_create(
    source_item_id: str,
    target_item_id: str,
    relation_type: str,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Cria uma relação entre dois itens já existentes, sem precisar passar por item_save.

    **Use quando:** Ligar dois itens que já existem, sem reescrever nenhum dos dois.
    **Retorna:** {id, source_item_id, target_item_id, relation_type}.
    **Exemplo:** relation_create(source_item_id="...", target_item_id="...",
        relation_type="depends_on")
    **Notas:** relation_type: related_to, depends_on, implements, references, supersedes,
        derived_from. `supersedes` marca o alvo como substituído (sai da busca e do contexto,
        sem perder o histórico). Se a connection tem repositório git em modo `direct`, o item
        de origem é republicado com a relação nova.
    """
    if relation_type not in RELATION_TYPES:
        raise ValidationError(
            f"relation_type inválido: {relation_type}. Válidos: {', '.join(RELATION_TYPES)}"
        )
    rel = RelationService(connection_id=connection_id).create_published(
        source_item_id, target_item_id, relation_type
    )
    return {
        "id": rel.id,
        "source_item_id": rel.source_item_id,
        "target_item_id": rel.target_item_id,
        "relation_type": rel.relation_type,
    }


def relation_delete(relation_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Remove uma relação entre itens (o id vem em item_get → relations).

    **Use quando:** Uma relação foi criada por engano.
    **Retorna:** {status: deleted, id}.
    **Exemplo:** relation_delete(relation_id="...")
    **Notas:** Remover um supersedes não reativa o alvo: ajuste o status com item_save. Se a
        connection tem repositório git em modo `direct`, o item de origem é republicado sem
        essa relação; em modo `pr` a relação some do índice, mas a republicação pendente de
        revisão fica para uma versão futura.
    """
    RelationService(connection_id=connection_id).delete_published(relation_id)
    return {"status": "deleted", "id": relation_id}


# --------------------------------------------------------------------------------------
# tag / label (antes: vocabulary(kind=, action=))
# --------------------------------------------------------------------------------------


def tag_list(connection_id: str | None = None) -> Any:
    """Lista as tags (livres) já usadas em algum item.

    **Use quando:** Reaproveitar tags existentes antes de criar variações.
    **Retorna:** [{id, name}].
    **Exemplo:** tag_list()
    """
    return [{"id": r.id, "name": r.name} for r in TagService(connection_id=connection_id).list()]


def tag_create(name: str, connection_id: str | None = None) -> Any:
    """Cria uma tag. Também pode ser criada direto no item_save.

    **Use quando:** Registrar uma tag nova fora do item_save.
    **Retorna:** {id, name}.
    **Exemplo:** tag_create(name="lgpd")
    """
    row = TagService(connection_id=connection_id).create(name)
    return {"id": row.id, "name": row.name}


def tag_delete(id: str, connection_id: str | None = None) -> Any:
    """Remove uma tag.

    **Use quando:** Remover uma tag que não faz mais sentido.
    **Retorna:** {status: deleted}.
    **Exemplo:** tag_delete(id="...")
    """
    TagService(connection_id=connection_id).delete(id)
    return {"status": "deleted", "id": id}


def label_list(connection_id: str | None = None) -> Any:
    """Lista os labels (lista controlada).

    **Use quando:** Ver os labels já cadastrados.
    **Retorna:** [{id, name}].
    **Exemplo:** label_list()
    """
    return [{"id": r.id, "name": r.name} for r in LabelService(connection_id=connection_id).list()]


def label_create(name: str, connection_id: str | None = None) -> Any:
    """Cria um label.

    **Use quando:** Registrar um label novo na lista controlada.
    **Retorna:** {id, name}.
    **Exemplo:** label_create(name="lgpd")
    """
    row = LabelService(connection_id=connection_id).create(name)
    return {"id": row.id, "name": row.name}


def label_delete(id: str, connection_id: str | None = None) -> Any:
    """Remove um label.

    **Use quando:** Remover um label que não faz mais sentido.
    **Retorna:** {status: deleted}.
    **Exemplo:** label_delete(id="...")
    """
    LabelService(connection_id=connection_id).delete(id)
    return {"status": "deleted", "id": id}


# --------------------------------------------------------------------------------------
# connection: criar/listar/remover uma connection a partir de uma pasta local
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
        "is_catalog": conn.id == DEFAULT_CONNECTION_ID,
    }


def connection_create(
    name: str, path: str, remote_url: str | None = None, review_mode: str = "direct"
) -> Any:
    """Cria uma connection: um repositório git numa pasta local (onde os items não-secretos
    são guardados como arquivo Markdown).

    **Use quando:** Começar a guardar conhecimento numa pasta que você já escolheu (um
        repositório próprio, com ou sem GitHub).
    **Retorna:** {id, name, path, remote_url, review_mode, enabled}.
    **Exemplo:** connection_create(name="Polara", path="/home/user/polara-knowledge")
    **Notas:** `path` precisa ser uma pasta existente, absoluta, fora da home de dados do
        Knowledge OS. Se já for um repositório git, é usado como está; senão, vira um
        (`git init`, preservando o que já tiver dentro). Com `remote_url`, `path` é o destino
        do clone.
    """
    conn = ConnectionService().create(name, path, remote_url=remote_url, review_mode=review_mode)
    return _connection_view(conn)


def connection_list() -> Any:
    """Lista as connections (a `default`, catálogo, primeiro).

    **Use quando:** Ver as connections já cadastradas.
    **Retorna:** [{id, name, path, remote_url, review_mode, enabled, is_default, is_catalog}].
    **Exemplo:** connection_list()
    """
    return [_connection_view(c) for c in ConnectionService().list()]


def connection_delete(id: str) -> dict[str, Any]:
    """Remove uma connection do cadastro. Não apaga a pasta nem o índice: são dados do
    usuário, e removê-los sem confirmação explícita é destrutivo demais pra fazer aqui.

    **Use quando:** Parar de usar uma connection sem apagar os dados dela.
    **Retorna:** {status: deleted|not_found, id}.
    **Exemplo:** connection_delete(id="...")
    """
    deleted = ConnectionService().delete(id)
    return {"status": "deleted" if deleted else "not_found", "id": id}


def register(mcp: FastMCP) -> None:
    """Registra as ferramentas (a última, `health_check`, é registrada em `main.py`)."""
    for fn in (
        workspace_list,
        workspace_create,
        workspace_rename,
        workspace_merge,
        workspace_delete,
        project_list,
        project_create,
        project_rename,
        project_merge,
        project_delete,
        subject_list,
        subject_create,
        subject_rename,
        subject_merge,
        subject_delete,
        repo,
        context_get,
        item_search,
        item_get,
        item_save,
        item_delete,
        relation_create,
        relation_delete,
        tag_list,
        tag_create,
        tag_delete,
        label_list,
        label_create,
        label_delete,
        connection_create,
        connection_list,
        connection_delete,
    ):
        mcp.tool()(fn)
