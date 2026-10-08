"""Rotas de projects e subjects (v2; id = slug do nome, único dentro do pai).

Nas rotas por id, `workspace_id` (query) desfaz a ambiguidade quando o mesmo project existe em
mais de um workspace (ex.: `geral`). As listas vêm de `ProjectService.rows()` /
`SubjectService.rows()` (com `scope` efetivo e explícito) e indicam de onde vem o herdado.
"""

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.routes._common import chain_source
from knowledge_os.api.schemas.requests import (
    ProjectCreate,
    ProjectUpdate,
    SubjectCreate,
    SubjectUpdate,
)
from knowledge_os.api.schemas.responses import ProjectRow, SubjectRow
from knowledge_os.exceptions import NotFoundError
from knowledge_os.services.brain import Brain
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.subject_service import SubjectService

router = APIRouter()


def _project_rows(cid: str, ws_id: str) -> list[dict[str, Any]]:
    ws = Brain(cid).snapshot.workspace(ws_id)
    return [{**row, "scope_inherited_from": None if row["scope_explicit"]
             else chain_source(("workspace", ws.scope))}
            for row in ProjectService(cid).rows(ws.id)]


def _project_row(cid: str, ws_id: str, pj_id: str) -> dict[str, Any]:
    for row in _project_rows(cid, ws_id):
        if row["id"] == pj_id:
            return row
    raise NotFoundError(f"Project não encontrado: {pj_id}")


def _subject_rows(cid: str, ws_id: str, pj_id: str) -> list[dict[str, Any]]:
    snap = Brain(cid).snapshot
    ws = snap.workspace(ws_id)
    pj = snap.project(ws.id, pj_id)
    return [{**row, "workspace_id": ws.id, "project_id": pj.id,
             "scope_inherited_from": None if row["scope_explicit"]
             else chain_source(("project", pj.scope), ("workspace", ws.scope))}
            for row in SubjectService(cid).rows(ws.id, pj.id)]


def _subject_row(cid: str, ws_id: str, pj_id: str, sj_id: str) -> dict[str, Any]:
    for row in _subject_rows(cid, ws_id, pj_id):
        if row["id"] == sj_id:
            return row
    raise NotFoundError(f"Subject não encontrado: {sj_id}")


# ---------------------------------------------------------------------------- projects


@router.get("/projects", response_model=list[ProjectRow])
def list_projects(workspace_id: str | None = None, cid: str = Depends(get_connection_id)):
    if workspace_id:
        return _project_rows(cid, workspace_id)
    return [row for ws in Brain(cid).snapshot.workspaces() for row in _project_rows(cid, ws.id)]


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectRow)
def create_project(req: ProjectCreate, cid: str = Depends(get_connection_id)):
    pj = ProjectService(cid).create(req.workspace_id, req.name, req.description, req.scope)
    return _project_row(cid, pj.workspace_id, pj.id)


@router.get("/projects/{id}", response_model=ProjectRow)
def get_project(id: str, workspace_id: str | None = None, cid: str = Depends(get_connection_id)):
    pj = ProjectService(cid).find_by_id(id, workspace_id)
    return _project_row(cid, pj.workspace_id, pj.id)


@router.put("/projects/{id}", response_model=ProjectRow)
def update_project(
    id: str, req: ProjectUpdate, workspace_id: str | None = None,
    cid: str = Depends(get_connection_id),
):
    """Só o que vier muda: `name` renomeia, `scope` grava (`""` volta a herdar)."""
    svc = ProjectService(cid)
    pj = svc.find_by_id(id, workspace_id)
    updated = svc.update(pj.workspace_id, pj.id, req.name, req.description, req.scope)
    return _project_row(cid, updated.workspace_id, updated.id)


@router.delete("/projects/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    id: str, workspace_id: str | None = None, cid: str = Depends(get_connection_id)
) -> Response:
    svc = ProjectService(cid)
    pj = svc.find_by_id(id, workspace_id)
    svc.delete(pj.workspace_id, pj.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------- subjects


@router.get("/subjects", response_model=list[SubjectRow])
def list_subjects(workspace_id: str, project_id: str, cid: str = Depends(get_connection_id)):
    return _subject_rows(cid, workspace_id, project_id)


@router.post("/subjects", status_code=status.HTTP_201_CREATED, response_model=SubjectRow)
def create_subject(req: SubjectCreate, cid: str = Depends(get_connection_id)):
    sj = SubjectService(cid).create(req.workspace_id, req.project_id, req.name,
                                    req.description, req.scope)
    return _subject_row(cid, sj.workspace_id, sj.project_id, sj.id)


@router.put("/subjects/{id}", response_model=SubjectRow)
def update_subject(id: str, req: SubjectUpdate, workspace_id: str, project_id: str,
                   cid: str = Depends(get_connection_id)):
    """Só o que vier muda: `name` renomeia, `scope` grava (`""` volta a herdar)."""
    sj = SubjectService(cid).update(workspace_id, project_id, id, req.name, req.description,
                                    req.scope)
    return _subject_row(cid, sj.workspace_id, sj.project_id, sj.id)


@router.delete("/subjects/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(id: str, workspace_id: str, project_id: str,
                   cid: str = Depends(get_connection_id)) -> Response:
    """Os itens do subject ficam no project, sem subject."""
    if not SubjectService(cid).delete(workspace_id, project_id, id):
        raise NotFoundError(f"Subject não encontrado: {id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
