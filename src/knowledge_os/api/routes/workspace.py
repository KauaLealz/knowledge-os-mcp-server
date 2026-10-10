"""Rotas de workspaces (v2; id = slug do nome): lista por `WorkspaceService.rows()` (com
`scope` efetivo e explícito e as contagens), criar/atualizar com `scope`, apagar, a árvore da
sidebar e o grafo de um escopo (workspace, project ou subject)."""

from fastapi import APIRouter, Depends, Response, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import WorkspaceCreate, WorkspaceUpdate
from knowledge_os.api.schemas.responses import (
    ScopeGraph,
    ScopeNode,
    TreeItem,
    TreeProject,
    TreeSubject,
    WorkspaceRow,
    WorkspaceTree,
)
from knowledge_os.exceptions import NotFoundError
from knowledge_os.services.brain import Brain, is_expired
from knowledge_os.services.item_file import slugify
from knowledge_os.services.workspace_service import WorkspaceService, effective

router = APIRouter()


def _row(cid: str, ws_id: str) -> dict:
    for row in WorkspaceService(cid).rows():
        if row["id"] == ws_id:
            return row
    raise NotFoundError(f"Workspace não encontrado: {ws_id}")


@router.get("/workspaces", response_model=list[WorkspaceRow])
def list_workspaces(cid: str = Depends(get_connection_id)):
    return WorkspaceService(cid).rows()


@router.post("/workspaces", status_code=status.HTTP_201_CREATED, response_model=WorkspaceRow)
def create_workspace(req: WorkspaceCreate, cid: str = Depends(get_connection_id)):
    ws = WorkspaceService(cid).create(req.name, req.description, req.scope)
    return _row(cid, ws.id)


@router.get("/workspaces/{id}", response_model=WorkspaceRow)
def get_workspace(id: str, cid: str = Depends(get_connection_id)):
    return _row(cid, WorkspaceService(cid).get(id).id)


@router.put("/workspaces/{id}", response_model=WorkspaceRow)
def update_workspace(id: str, req: WorkspaceUpdate, cid: str = Depends(get_connection_id)):
    """Só o que vier muda: `name` renomeia, `scope` grava (`""` volta a herdar)."""
    ws = WorkspaceService(cid).update(id, req.name, req.description, req.scope)
    return _row(cid, ws.id)


@router.delete("/workspaces/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(id: str, cid: str = Depends(get_connection_id)) -> Response:
    svc = WorkspaceService(cid)
    svc.delete(svc.get(id).id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workspaces/{id}/tree", response_model=WorkspaceTree)
def workspace_tree(id: str, cid: str = Depends(get_connection_id)):
    """Projects (por nome) com seus subjects (por nome) e itens (por título)."""
    snap = Brain(cid).snapshot
    ws = snap.workspace(id)
    out = []
    for pj in snap.projects(ws.id):
        records = sorted(snap.items_in(ws.id, pj.id), key=lambda r: (r.title, r.id))
        subjects = snap.subjects(ws.id, pj.id)
        by_subject: dict[str, list[TreeItem]] = {sj.id: [] for sj in subjects}
        loose: list[TreeItem] = []
        for r in records:
            tree_item = TreeItem(
                id=r.id, key=r.key, title=r.title, type=r.type, subtype=r.subtype,
                status=r.status, scope=snap.effective_scope(r), updated_at=r.updated_at,
                expired=is_expired(r),
            )
            sj_id = slugify(r.subject) if r.subject else None
            (by_subject[sj_id] if sj_id in by_subject else loose).append(tree_item)
        out.append(TreeProject(
            id=pj.id, name=pj.name, description=pj.description,
            scope=effective(pj.scope, ws.scope), scope_explicit=pj.scope,
            item_count=len(records), items=loose,
            subjects=[TreeSubject(id=sj.id, name=sj.name, description=sj.description,
                                  scope=effective(sj.scope, pj.scope, ws.scope),
                                  scope_explicit=sj.scope, item_count=len(by_subject[sj.id]),
                                  items=by_subject[sj.id]) for sj in subjects],
        ))
    return WorkspaceTree(projects=out)


@router.get("/workspaces/{id}/graph", response_model=ScopeGraph)
def workspace_graph(
    id: str,
    project_id: str | None = None,
    subject_id: str | None = None,
    cid: str = Depends(get_connection_id),
):
    """Nós = itens do escopo (workspace inteiro, ou só um project/subject dele), no formato do
    nó do `item_graph` + onde o item mora; arestas = relações entre dois itens do escopo."""
    snap = Brain(cid).snapshot
    ws = snap.workspace(id)
    records = snap.items_in(ws.id, project_id or None, subject_id or None)
    nodes = [
        ScopeNode(
            key=r.key, id=r.id, type=r.type, subtype=r.subtype, title=r.title,
            summary=r.summary, scope=snap.effective_scope(r), status=r.status or "active",
            project_id=slugify(r.project or ""), project_name=r.project or "?",
            subject_id=slugify(r.subject) if r.subject else None, subject_name=r.subject,
        )
        for r in records
    ]
    ids = {r.id for r in records}
    edges = [
        {"from": rel.source_item_id, "type": rel.relation_type, "to": rel.target_item_id}
        for r in records for rel in snap.relations_of(r)
        if rel.target_item_id in ids
    ]
    return ScopeGraph(nodes=nodes, edges=edges)
