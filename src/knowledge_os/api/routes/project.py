"""Rotas de projects (id = slug do nome, único dentro do workspace).

Nas rotas por id, `workspace_id` (query) desfaz a ambiguidade quando o mesmo project existe em
mais de um workspace (ex.: `geral`).
"""

from fastapi import APIRouter, Depends, Response, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import ProjectCreate, ProjectUpdate
from knowledge_os.api.schemas.responses import ProjectResponse, ProjectStats
from knowledge_os.services.brain import Brain
from knowledge_os.services.project_service import ProjectService

router = APIRouter()


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(workspace_id: str | None = None, cid: str = Depends(get_connection_id)):
    svc = ProjectService(cid)
    return svc.list(workspace_id) if workspace_id else svc.list_all()


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
def create_project(req: ProjectCreate, cid: str = Depends(get_connection_id)):
    return ProjectService(cid).create(req.workspace_id, req.name, req.description)


@router.get("/projects/{id}", response_model=ProjectResponse)
def get_project(id: str, workspace_id: str | None = None, cid: str = Depends(get_connection_id)):
    return ProjectService(cid).find_by_id(id, workspace_id)


@router.put("/projects/{id}", response_model=ProjectResponse)
def update_project(
    id: str, req: ProjectUpdate, workspace_id: str | None = None,
    cid: str = Depends(get_connection_id),
):
    svc = ProjectService(cid)
    pj = svc.find_by_id(id, workspace_id)
    return svc.update(pj.workspace_id, pj.id, req.name, req.description)


@router.delete("/projects/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    id: str, workspace_id: str | None = None, cid: str = Depends(get_connection_id)
) -> Response:
    svc = ProjectService(cid)
    pj = svc.find_by_id(id, workspace_id)
    svc.delete(pj.workspace_id, pj.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{id}/stats", response_model=ProjectStats)
def project_stats(
    id: str, workspace_id: str | None = None, cid: str = Depends(get_connection_id)
):
    pj = ProjectService(cid).find_by_id(id, workspace_id)
    return ProjectStats(items=len(Brain(cid).snapshot.items_in(pj.workspace_id, pj.id)))
