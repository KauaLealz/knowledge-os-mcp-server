"""Ferramentas MCP do Knowledge OS: 14 ferramentas, sem conceito de perfil.

Antes havia dois perfis (`agent` com 6 ferramentas, `all` com todas): o perfil foi
removido — todo cliente MCP vê as mesmas 14 ferramentas. `workspace`/`project`/`subject`
e `repo` usam `action=` para agrupar create/list/rename/merge/delete (ou link/list/unlink)
numa única ferramenta cada, em vez de uma função por operação.
"""

import base64
from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from sqlalchemy import func, select

from knowledge_os.config import CATALOG_ID, EXPORTS_DIR, ConfigManager
from knowledge_os.db.models import Item, Project, Workspace
from knowledge_os.db.session import connection_id_of, default_connection_id, get_engine, get_session
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.schemas.artifact_schemas import ArtifactCreate, ArtifactResponse
from knowledge_os.schemas.item_schemas import ItemResponse, ItemSearchRequest, ItemSearchResult
from knowledge_os.schemas.project_schemas import ProjectResponse
from knowledge_os.schemas.relation_schemas import RelationListResponse
from knowledge_os.schemas.workspace_schemas import WorkspaceResponse
from knowledge_os.services.artifact_service import ArtifactService
from knowledge_os.services.context_service import ContextService
from knowledge_os.services.git_repo_service import GitRepoService
from knowledge_os.services.import_export_service import ImportExportService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.label_service import LabelService
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.services.repo_service import RepoService
from knowledge_os.services.secret_service import SecretService
from knowledge_os.services.subject_service import SubjectService
from knowledge_os.services.tag_service import TagService
from knowledge_os.services.workspace_service import WorkspaceService

MAX_GET = 20


# --------------------------------------------------------------------------------------
# 1-3. workspace / project / subject: CRUD + rename + merge, por action=
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
            projects = list(session.scalars(
                select(Project).where(Project.workspace_id == ws.id).order_by(Project.name)))
            rows = [{"name": d.name, "items": counts.get(d.id, 0)} for d in projects]
            out.append({"workspace": ws.name, "description": ws.description,
                        "items": sum(r["items"] for r in rows), "projects": rows})
    finally:
        session.close()
    if workspace and not out:
        raise NotFoundError(f"Workspace não encontrado: {workspace}")
    return out


def workspace(
    action: str,
    name: str | None = None,
    new_name: str | None = None,
    source: str | None = None,
    target: str | None = None,
    description: str | None = None,
    confirm: bool = False,
    connection_id: str | None = None,
) -> Any:
    """Workspace = contexto de trabalho (empresa, cliente, Pessoal, Global).

    **Use quando:** Organizar, renomear, unificar ou remover workspaces.
    **Retorna:** list → [{name, description, projects, items}]; create → {id, name,
        description}; rename → {id, name}; merge → {merged_projects, renamed_collisions};
        delete sem confirm → {status: preview, would_delete}; com confirm →
        {status: deleted, ...}.
    **Exemplo:** workspace(action="list") · workspace(action="create", name="Polara") ·
        workspace(action="rename", name="polara", new_name="Polara") ·
        workspace(action="merge", source="Polara Antiga", target="Polara") ·
        workspace(action="delete", name="Teste", confirm=True)
    **Notas:** merge move os projects de source para target (projects homônimos são
        mesclados por nome, não duplicados) e apaga source. delete sem confirm só mostra
        o preview; chame de novo com confirm=True para apagar de vez.
    """
    svc = WorkspaceService(connection_id=connection_id)
    if action == "list":
        rows = _location_tree(name, connection_id)
        return [{"name": r["workspace"], "description": r["description"],
                  "projects": len(r["projects"]), "items": r["items"]} for r in rows]
    if action == "create":
        if not name:
            raise ValidationError("create exige name")
        row = svc.create(name, description)
        return {"id": row.id, "name": row.name, "description": row.description}
    if action == "rename":
        if not name or not new_name:
            raise ValidationError("rename exige name e new_name")
        row = svc.rename(name, new_name)
        return {"id": row.id, "name": row.name}
    if action == "merge":
        if not source or not target:
            raise ValidationError("merge exige source e target")
        return svc.merge(source, target)
    if action == "delete":
        if not name:
            raise ValidationError("delete exige name")
        preview = _location_tree(name, connection_id)[0]
        would = {"workspace": name, "projects": len(preview["projects"]),
                 "items": preview["items"]}
        if not confirm:
            return {"status": "preview", "would_delete": would}
        svc.delete(name)
        return {"status": "deleted", **would}
    raise ValidationError("action deve ser list, create, rename, merge ou delete")


def project(
    action: str,
    workspace: str,
    name: str | None = None,
    new_name: str | None = None,
    source: str | None = None,
    target: str | None = None,
    description: str | None = None,
    confirm: bool = False,
    connection_id: str | None = None,
) -> Any:
    """Project = o repositório dentro de um workspace (`Geral` guarda o que vale para todos).

    **Use quando:** Organizar, renomear, unificar ou remover projects de um workspace.
    **Retorna:** list → [{name, items}]; create → {id, name, description}; rename →
        {id, name}; merge → {merged_items, merged_subjects}; delete sem confirm →
        {status: preview, would_delete}; com confirm → {status: deleted, ...}.
    **Exemplo:** project(action="list", workspace="Polara") · project(action="create",
        workspace="Polara", name="projpro") · project(action="merge", workspace="Polara",
        source="projpro-old", target="projpro")
    **Notas:** `workspace` é sempre obrigatório (nome ou id). merge move os items de source
        para target (subjects homônimos mesclados por nome) e apaga source.
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    svc = ProjectService(connection_id=connection_id)
    if action == "list":
        rows = _location_tree(workspace, connection_id)[0]["projects"]
        return rows
    if action == "create":
        if not name:
            raise ValidationError("create exige name")
        row = svc.create(ws_id, name, description)
        return {"id": row.id, "name": row.name, "description": row.description}
    if action == "rename":
        if not name or not new_name:
            raise ValidationError("rename exige name e new_name")
        row = svc.rename(ws_id, name, new_name)
        return {"id": row.id, "name": row.name}
    if action == "merge":
        if not source or not target:
            raise ValidationError("merge exige source e target")
        return svc.merge(ws_id, source, target)
    if action == "delete":
        if not name:
            raise ValidationError("delete exige name")
        preview = _location_tree(workspace, connection_id)[0]
        match = [d for d in preview["projects"] if d["name"] == name]
        if not match:
            raise NotFoundError(f"Project não encontrado: {name}")
        would = {"project": name, "items": match[0]["items"]}
        if not confirm:
            return {"status": "preview", "would_delete": would}
        svc.delete(ws_id, name)
        return {"status": "deleted", **would}
    raise ValidationError("action deve ser list, create, rename, merge ou delete")


def subject(
    action: str,
    workspace: str,
    project: str,
    name: str | None = None,
    new_name: str | None = None,
    source: str | None = None,
    target: str | None = None,
    description: str | None = None,
    confirm: bool = False,
    connection_id: str | None = None,
) -> Any:
    """Subject = assunto opcional que agrupa items dentro de um project.

    **Use quando:** Organizar, renomear, unificar ou remover subjects de um project.
    **Retorna:** list → [{name, items}]; create → {id, name, description}; rename →
        {id, name}; merge → {merged_items}; delete sem confirm → {status: preview,
        would_delete: {items_sem_assunto}}; com confirm → {status: deleted}.
    **Exemplo:** subject(action="list", workspace="Polara", project="app") ·
        subject(action="create", workspace="Polara", project="app", name="pagamentos")
    **Notas:** `workspace`+`project` são sempre obrigatórios. delete nunca apaga item, só
        desvincula (subject_id = None); o preview mostra quantos items ficariam sem assunto.
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    pj_id = ProjectService(connection_id=connection_id).get(ws_id, project).id
    svc = SubjectService(connection_id=connection_id)
    if action == "list":
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
    if action == "create":
        if not name:
            raise ValidationError("create exige name")
        row = svc.create(pj_id, name, description)
        return {"id": row.id, "name": row.name, "description": row.description}
    if action == "rename":
        if not name or not new_name:
            raise ValidationError("rename exige name e new_name")
        row = svc.rename(pj_id, name, new_name)
        return {"id": row.id, "name": row.name}
    if action == "merge":
        if not source or not target:
            raise ValidationError("merge exige source e target")
        return svc.merge(pj_id, source, target)
    if action == "delete":
        if not name:
            raise ValidationError("delete exige name")
        sj = svc.get(pj_id, name)
        session = get_session(get_engine(connection_id) if connection_id else get_engine())
        try:
            orphaned = session.scalar(
                select(func.count()).select_from(Item).where(Item.subject_id == sj.id)
            )
        finally:
            session.close()
        if not confirm:
            return {"status": "preview", "would_delete": {"subject": name,
                                                            "items_sem_assunto": orphaned}}
        svc.delete(pj_id, name)
        return {"status": "deleted", "subject": name, "items_sem_assunto": orphaned}
    raise ValidationError("action deve ser list, create, rename, merge ou delete")


# --------------------------------------------------------------------------------------
# 4. repo: link / list / unlink
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
# 5-8. context_get / item_search / item_get / item_save
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
        workspace_id=workspace_id, project_id=project_id, subject_id=subject_id, query=query,
        types=types, memory_classes=memory_classes, limit=limit,
    )
    rows = svc.search(
        req.workspace_id, req.project_id, req.query, req.subject_id, req.types,
        req.memory_classes, req.limit, include_inactive=include_inactive,
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
    """Lê itens completos (content, tags, relações, anexos) por id e/ou key, vários de uma vez.

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
        caso de `id`, id, created_at, access_count, tags, labels, relations e artifacts do item
        não mudam — só as FKs de localização.
    **Exemplo (upsert):** item_save(repo=".", items=[{"key": "regra/money", "type": "rule",
        "title": "Money em pagamentos", "summary": "Valores em Money, nunca double",
        "content": "...", "scope_paths": ["src/payments/**"], "source": "PAY-142"}])
    **Exemplo (aposentar):** item_save(repo=".", items=[{"key": "regra/x",
        "status": "deprecated"}])
    **Exemplo (substituir):** item_save(repo=".", items=[{"key": "proc/deploy-v2", ...,
        "relations": [{"type": "supersedes", "target": "proc/deploy"}]}])
    **Campos:** type (rule, insight, procedure, pattern, knowledge, context, artifact, task),
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
# 9-11. item_delete / relation_delete / vocabulary
# --------------------------------------------------------------------------------------


def item_delete(item_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Remove um item de vez (com tags, relações e anexos). Destrutivo.

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


def vocabulary(
    kind: str = "tags",
    action: str = "list",
    name: str | None = None,
    id: str | None = None,
    connection_id: str | None = None,
) -> Any:
    """Vocabulário da base: tags (livres) e labels (lista controlada).

    **Use quando:** Reaproveitar tags existentes antes de criar variações, ou gerir labels.
    **Retorna:** list → [{id, name}]; create → {id, name}; delete → {status: deleted}.
    **Exemplo:** vocabulary(kind="tags") · vocabulary(kind="labels", action="create", name="lgpd")
    **Notas:** kind: tags | labels. action: list | create (name) | delete (id). Tags também são
        criadas direto no item_save.
    """
    services = {"tags": TagService, "labels": LabelService}
    if kind not in services:
        raise ValidationError("kind deve ser tags ou labels")
    svc = services[kind](connection_id=connection_id)
    if action == "list":
        return [{"id": r.id, "name": r.name} for r in svc.list()]
    if action == "create":
        if not name:
            raise ValidationError("create exige name")
        row = svc.create(name)
        return {"id": row.id, "name": row.name}
    if action == "delete":
        if not id:
            raise ValidationError("delete exige id")
        svc.delete(id)
        return {"status": "deleted", "id": id}
    raise ValidationError("action deve ser list, create ou delete")


# --------------------------------------------------------------------------------------
# 12-13. artifact / backup
# --------------------------------------------------------------------------------------


def artifact(
    action: str,
    item_id: str | None = None,
    file_path: str | None = None,
    artifact_id: str | None = None,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Anexa um arquivo local a um item ou lê o conteúdo de um anexo.

    **Use quando:** O valor do item é um arquivo (diagrama, template, script), ou é preciso
        o arquivo em si (confira file_size em item_get antes).
    **Retorna:** attach → metadados do anexo (id, filename, file_size, mime_type); get →
        {artifact, content_base64}.
    **Exemplo:** artifact(action="attach", item_id="...", file_path="C:/docs/arquitetura.png")
        · artifact(action="get", artifact_id="...")
    **Notas:** Use só caminhos que o usuário indicou (attach). A lista de anexos de um item vem
        em item_get → artifacts, até 100 MB por arquivo.
    """
    if action == "attach":
        if not item_id or not file_path:
            raise ValidationError("attach exige item_id e file_path")
        data = ArtifactCreate(item_id=item_id, file_path=file_path)
        art = ArtifactService(connection_id=connection_id).attach(data.item_id, data.file_path)
        return ArtifactResponse.model_validate(art).model_dump(mode="json")
    if action == "get":
        if not artifact_id:
            raise ValidationError("get exige artifact_id")
        art, content = ArtifactService(connection_id=connection_id).get(artifact_id)
        return {
            "artifact": ArtifactResponse.model_validate(art).model_dump(mode="json"),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
    raise ValidationError("action deve ser attach ou get")


def backup(
    action: str,
    workspace: str | None = None,
    project: str | None = None,
    file_path: str | None = None,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Exporta um workspace (ou project) para ZIP em `<home>/exports`, ou importa um ZIP desses.

    **Use quando:** Antes de mudanças grandes, para levar conhecimento a outra máquina, ou
        para restaurar um backup.
    **Retorna:** export → {status: ok, file_path, size_mb}; import → {status: ok, ...workspace
        ou project criado}.
    **Exemplo:** backup(action="export", workspace="agenda-api") · backup(action="export",
        workspace="agenda-api", project="projpro") · backup(action="import",
        file_path="C:/x/workspace_....zip")
    **Notas:** import usa só caminhos que o usuário indicou; nome de workspace já existente é
        recusado. O workspace importado ganha ids novos.
    """
    if action == "export":
        if not workspace:
            raise ValidationError("export exige workspace")
        ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
        svc = ImportExportService(connection_id=connection_id)
        if project:
            pj_id = ProjectService(connection_id=connection_id).get(ws_id, project).id
            data, prefix = svc.export_project(ws_id, pj_id), f"project_{pj_id}"
        else:
            data, prefix = svc.export_workspace(ws_id), f"workspace_{ws_id}"
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = EXPORTS_DIR / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.zip"
        path.write_bytes(data)
        return {"status": "ok", "file_path": str(path), "size_mb": round(len(data) / 1048576, 2)}
    if action == "import":
        if not file_path:
            raise ValidationError("import exige file_path")
        svc = ImportExportService(connection_id=connection_id)
        if workspace:
            ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
            dm = svc.import_project(ws_id, file_path)
            return {"status": "ok", **ProjectResponse.model_validate(dm).model_dump(mode="json")}
        ws = svc.import_workspace(file_path)
        return {"status": "ok", **WorkspaceResponse.model_validate(ws).model_dump(mode="json")}
    raise ValidationError("action deve ser export ou import")


def register(mcp: FastMCP) -> None:
    """Registra estas 13 ferramentas (a 14ª, `health_check`, é registrada em `main.py`)."""
    for fn in (
        workspace, project, subject, repo,
        context_get, item_search, item_get, item_save,
        item_delete, relation_delete, vocabulary,
        artifact, backup,
    ):
        mcp.tool()(fn)
