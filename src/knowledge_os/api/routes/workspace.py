"""Rotas de workspaces (ids = slug do nome)."""

from fastapi import APIRouter, Depends, Response, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import WorkspaceCreate, WorkspaceUpdate
from knowledge_os.api.schemas.responses import (
    GraphEdge,
    GraphNode,
    TreeItem,
    TreeProject,
    TreeSubject,
    WorkspaceGraph,
    WorkspaceResponse,
    WorkspaceStats,
    WorkspaceTree,
)
from knowledge_os.services.brain import Brain
from knowledge_os.services.item_file import slugify
from knowledge_os.services.workspace_service import WorkspaceService

router = APIRouter()


@router.get("/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces(cid: str = Depends(get_connection_id)):
    return WorkspaceService(cid).list()


@router.post("/workspaces", status_code=status.HTTP_201_CREATED, response_model=WorkspaceResponse)
def create_workspace(req: WorkspaceCreate, cid: str = Depends(get_connection_id)):
    return WorkspaceService(cid).create(req.name, req.description)


@router.get("/workspaces/{id}", response_model=WorkspaceResponse)
def get_workspace(id: str, cid: str = Depends(get_connection_id)):
    return WorkspaceService(cid).get(id)


@router.put("/workspaces/{id}", response_model=WorkspaceResponse)
def update_workspace(id: str, req: WorkspaceUpdate, cid: str = Depends(get_connection_id)):
    return WorkspaceService(cid).update(id, req.name, req.description)


@router.delete("/workspaces/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(id: str, cid: str = Depends(get_connection_id)) -> Response:
    svc = WorkspaceService(cid)
    svc.delete(svc.get(id).id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workspaces/{id}/stats", response_model=WorkspaceStats)
def workspace_stats(id: str, cid: str = Depends(get_connection_id)):
    snap = Brain(cid).snapshot
    ws = snap.workspace(id)
    return WorkspaceStats(projects=len(snap.projects(ws.id)), items=len(snap.items_in(ws.id)))


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
                id=r.id, title=r.title, type=r.type, memory_class=r.memory_class,
                confidence=r.confidence, updated_at=r.updated_at,
            )
            sj_id = slugify(r.subject) if r.subject else None
            (by_subject[sj_id] if sj_id in by_subject else loose).append(tree_item)
        out.append(TreeProject(
            id=pj.id, name=pj.name, description=pj.description, item_count=len(records),
            items=loose,
            subjects=[TreeSubject(id=sj.id, name=sj.name, item_count=len(by_subject[sj.id]),
                                  items=by_subject[sj.id]) for sj in subjects],
        ))
    return WorkspaceTree(projects=out)


@router.get("/workspaces/{id}/graph", response_model=WorkspaceGraph)
def workspace_graph(
    id: str,
    project_id: str | None = None,
    subject_id: str | None = None,
    cid: str = Depends(get_connection_id),
):
    """Nós = itens do escopo (workspace inteiro, ou só um project/subject dele); arestas =
    relações entre dois itens do mesmo escopo."""
    snap = Brain(cid).snapshot
    ws = snap.workspace(id)
    records = snap.items_in(ws.id, project_id or None, subject_id or None)
    nodes = [
        GraphNode(
            id=r.id, title=r.title, type=r.type, project_id=slugify(r.project or ""),
            project_name=r.project or "?",
            subject_id=slugify(r.subject) if r.subject else None, subject_name=r.subject,
            status=r.status,
        )
        for r in records
    ]
    ids = {r.id for r in records}
    edges = [
        GraphEdge(source=rel.source_item_id, target=rel.target_item_id,
                  relation_type=rel.relation_type)
        for r in records for rel in snap.relations_of(r)
        if rel.target_item_id in ids
    ]
    return WorkspaceGraph(nodes=nodes, edges=edges)
