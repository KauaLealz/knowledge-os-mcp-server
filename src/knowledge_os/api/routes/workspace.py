"""Rotas de workspaces."""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_os.api.deps import get_artifacts_dir, get_connection_id, get_session_dep
from knowledge_os.api.routes._helpers import get_or_404
from knowledge_os.api.schemas.requests import WorkspaceCreate, WorkspaceUpdate
from knowledge_os.api.schemas.responses import (
    GraphEdge,
    GraphNode,
    TreeItem,
    TreeProject,
    WorkspaceGraph,
    WorkspaceResponse,
    WorkspaceStats,
    WorkspaceTree,
)
from knowledge_os.db.models import Item, Project, Workspace
from knowledge_os.exceptions import ValidationError
from knowledge_os.services.import_export_service import ImportExportService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.services.workspace_service import WorkspaceService

router = APIRouter()


@router.get("/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces(
    session: Session = Depends(get_session_dep), cid: str = Depends(get_connection_id)
):
    return WorkspaceService(session, cid).list()


@router.post("/workspaces", status_code=status.HTTP_201_CREATED, response_model=WorkspaceResponse)
def create_workspace(
    req: WorkspaceCreate,
    session: Session = Depends(get_session_dep),
    cid: str = Depends(get_connection_id),
):
    return WorkspaceService(session, cid).create(req.name, req.description)


@router.post(
    "/workspaces/import", status_code=status.HTTP_201_CREATED, response_model=WorkspaceResponse
)
def import_workspace(
    file: UploadFile,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
    cid: str = Depends(get_connection_id),
):
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "import.zip"
        with zip_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return ImportExportService(session, artifacts_dir, cid).import_workspace(str(zip_path))


@router.get("/workspaces/{id}", response_model=WorkspaceResponse)
def get_workspace(id: str, session: Session = Depends(get_session_dep)):
    return get_or_404(session, Workspace, id, "Workspace")


@router.put("/workspaces/{id}", response_model=WorkspaceResponse)
def update_workspace(
    id: str,
    req: WorkspaceUpdate,
    session: Session = Depends(get_session_dep),
    cid: str = Depends(get_connection_id),
):
    ws = get_or_404(session, Workspace, id, "Workspace")
    clash = session.scalar(
        select(Workspace.id).where(
            Workspace.name == req.name,
            Workspace.connection_id == cid,
            Workspace.id != id,
        )
    )
    if clash is not None:
        raise ValidationError(f"Workspace já existe: {req.name}")
    ws.name = req.name
    if req.description is not None:
        ws.description = req.description
    session.commit()
    session.refresh(ws)
    return ws


@router.delete("/workspaces/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    id: str,
    session: Session = Depends(get_session_dep),
    cid: str = Depends(get_connection_id),
) -> Response:
    ws = get_or_404(session, Workspace, id, "Workspace")
    WorkspaceService(session, cid).delete(ws.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workspaces/{id}/stats", response_model=WorkspaceStats)
def workspace_stats(id: str, session: Session = Depends(get_session_dep)):
    get_or_404(session, Workspace, id, "Workspace")
    projects = session.scalar(
        select(func.count()).select_from(Project).where(Project.workspace_id == id)
    )
    items = session.scalar(select(func.count()).select_from(Item).where(Item.workspace_id == id))
    return WorkspaceStats(projects=projects or 0, items=items or 0)


@router.get("/workspaces/{id}/tree", response_model=WorkspaceTree)
def workspace_tree(id: str, session: Session = Depends(get_session_dep)):
    """Projects (por nome) com seus items (por título), em duas queries."""
    get_or_404(session, Workspace, id, "Workspace")
    projects = session.scalars(
        select(Project).where(Project.workspace_id == id).order_by(Project.name)
    ).all()
    rows = session.execute(
        select(
            Item.id,
            Item.project_id,
            Item.title,
            Item.type,
            Item.memory_class,
            Item.confidence,
            Item.updated_at,
        )
        .where(Item.workspace_id == id)
        .order_by(Item.title, Item.id)
    ).all()
    by_project: dict[str, list[TreeItem]] = {d.id: [] for d in projects}
    for row in rows:
        if row.project_id in by_project:
            by_project[row.project_id].append(
                TreeItem(
                    id=row.id,
                    title=row.title,
                    type=row.type,
                    memory_class=row.memory_class,
                    confidence=row.confidence,
                    updated_at=row.updated_at,
                )
            )
    return WorkspaceTree(
        projects=[
            TreeProject(
                id=d.id,
                name=d.name,
                description=d.description,
                item_count=len(by_project[d.id]),
                items=by_project[d.id],
            )
            for d in projects
        ]
    )


@router.get("/workspaces/{id}/graph", response_model=WorkspaceGraph)
def workspace_graph(id: str, session: Session = Depends(get_session_dep)):
    """Nós = items do workspace; arestas = Relation entre dois items do workspace."""
    get_or_404(session, Workspace, id, "Workspace")
    rows = session.execute(
        select(Item.id, Item.title, Item.type, Item.project_id, Item.status).where(
            Item.workspace_id == id
        )
    ).all()
    nodes = [
        GraphNode(id=r.id, title=r.title, type=r.type, project_id=r.project_id, status=r.status)
        for r in rows
    ]
    edges = [
        GraphEdge(
            source=rel.source_item_id,
            target=rel.target_item_id,
            relation_type=rel.relation_type,
        )
        for rel in RelationService(session).list_for_workspace(id)
    ]
    return WorkspaceGraph(nodes=nodes, edges=edges)


@router.post("/workspaces/{id}/export")
def export_workspace(
    id: str,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
) -> Response:
    ws = get_or_404(session, Workspace, id, "Workspace")
    data = ImportExportService(session, artifacts_dir).export_workspace(id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="workspace-{ws.id}.zip"'},
    )
