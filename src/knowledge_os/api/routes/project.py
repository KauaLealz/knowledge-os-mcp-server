"""Rotas de projects."""

from pathlib import Path

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_os.api.deps import get_artifacts_dir, get_session_dep
from knowledge_os.api.routes._helpers import get_or_404
from knowledge_os.api.schemas.requests import ProjectCreate, ProjectUpdate
from knowledge_os.api.schemas.responses import ProjectResponse, ProjectStats
from knowledge_os.db.models import Item, Project
from knowledge_os.exceptions import ValidationError
from knowledge_os.services.import_export_service import ImportExportService
from knowledge_os.services.project_service import ProjectService

router = APIRouter()


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(workspace_id: str | None = None, session: Session = Depends(get_session_dep)):
    if workspace_id:
        return ProjectService(session).list(workspace_id)
    return list(session.scalars(select(Project).order_by(Project.created_at, Project.name)))


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
def create_project(req: ProjectCreate, session: Session = Depends(get_session_dep)):
    return ProjectService(session).create(req.workspace_id, req.name, req.description)


@router.get("/projects/{id}", response_model=ProjectResponse)
def get_project(id: str, session: Session = Depends(get_session_dep)):
    return get_or_404(session, Project, id, "Project")


@router.put("/projects/{id}", response_model=ProjectResponse)
def update_project(id: str, req: ProjectUpdate, session: Session = Depends(get_session_dep)):
    pj = get_or_404(session, Project, id, "Project")
    clash = session.scalar(
        select(Project.id).where(
            Project.workspace_id == pj.workspace_id, Project.name == req.name, Project.id != id
        )
    )
    if clash is not None:
        raise ValidationError(f"Project já existe no workspace: {req.name}")
    pj.name = req.name
    if req.description is not None:
        pj.description = req.description
    session.commit()
    session.refresh(pj)
    return pj


@router.delete("/projects/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(id: str, session: Session = Depends(get_session_dep)) -> Response:
    pj = get_or_404(session, Project, id, "Project")
    ProjectService(session).delete(pj.workspace_id, pj.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{id}/stats", response_model=ProjectStats)
def project_stats(id: str, session: Session = Depends(get_session_dep)):
    get_or_404(session, Project, id, "Project")
    items = session.scalar(select(func.count()).select_from(Item).where(Item.project_id == id))
    return ProjectStats(items=items or 0)


@router.post("/projects/{id}/export")
def export_project(
    id: str,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
) -> Response:
    pj = get_or_404(session, Project, id, "Project")
    data = ImportExportService(session, artifacts_dir).export_project(pj.workspace_id, id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="project-{pj.id}.zip"'},
    )
