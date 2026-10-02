"""Rotas de workspaces."""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.auth import verify_token
from src.api.deps import get_artifacts_dir, get_session_dep
from src.api.routes._helpers import get_or_404
from src.api.schemas.requests import WorkspaceCreate, WorkspaceUpdate
from src.api.schemas.responses import WorkspaceResponse, WorkspaceStats
from src.db.models import DEFAULT_CONNECTION_ID, Domain, Item, Workspace
from src.exceptions import ValidationError
from src.services.import_export_service import ImportExportService
from src.services.workspace_service import WorkspaceService

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces(session: Session = Depends(get_session_dep)):
    return WorkspaceService(session).list()


@router.post("/workspaces", status_code=status.HTTP_201_CREATED, response_model=WorkspaceResponse)
def create_workspace(req: WorkspaceCreate, session: Session = Depends(get_session_dep)):
    return WorkspaceService(session).create(req.name, req.description)


@router.post(
    "/workspaces/import", status_code=status.HTTP_201_CREATED, response_model=WorkspaceResponse
)
def import_workspace(
    file: UploadFile,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
):
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "import.zip"
        with zip_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return ImportExportService(session, artifacts_dir).import_workspace(str(zip_path))


@router.get("/workspaces/{id}", response_model=WorkspaceResponse)
def get_workspace(id: str, session: Session = Depends(get_session_dep)):
    return get_or_404(session, Workspace, id, "Workspace")


@router.put("/workspaces/{id}", response_model=WorkspaceResponse)
def update_workspace(id: str, req: WorkspaceUpdate, session: Session = Depends(get_session_dep)):
    ws = get_or_404(session, Workspace, id, "Workspace")
    clash = session.scalar(
        select(Workspace.id).where(
            Workspace.name == req.name,
            Workspace.connection_id == DEFAULT_CONNECTION_ID,
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
def delete_workspace(id: str, session: Session = Depends(get_session_dep)) -> Response:
    ws = get_or_404(session, Workspace, id, "Workspace")
    WorkspaceService(session).delete(ws.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workspaces/{id}/stats", response_model=WorkspaceStats)
def workspace_stats(id: str, session: Session = Depends(get_session_dep)):
    get_or_404(session, Workspace, id, "Workspace")
    domains = session.scalar(
        select(func.count()).select_from(Domain).where(Domain.workspace_id == id)
    )
    items = session.scalar(select(func.count()).select_from(Item).where(Item.workspace_id == id))
    return WorkspaceStats(domains=domains or 0, items=items or 0)


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
