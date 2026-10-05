"""Rotas de domains."""

from pathlib import Path

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_os.api.deps import get_artifacts_dir, get_session_dep
from knowledge_os.api.routes._helpers import get_or_404
from knowledge_os.api.schemas.requests import DomainCreate, DomainUpdate
from knowledge_os.api.schemas.responses import DomainResponse, DomainStats
from knowledge_os.db.models import Domain, Item
from knowledge_os.exceptions import ValidationError
from knowledge_os.services.domain_service import DomainService
from knowledge_os.services.import_export_service import ImportExportService

router = APIRouter()


@router.get("/domains", response_model=list[DomainResponse])
def list_domains(workspace_id: str | None = None, session: Session = Depends(get_session_dep)):
    if workspace_id:
        return DomainService(session).list(workspace_id)
    return list(session.scalars(select(Domain).order_by(Domain.created_at, Domain.name)))


@router.post("/domains", status_code=status.HTTP_201_CREATED, response_model=DomainResponse)
def create_domain(req: DomainCreate, session: Session = Depends(get_session_dep)):
    return DomainService(session).create(req.workspace_id, req.name, req.description)


@router.get("/domains/{id}", response_model=DomainResponse)
def get_domain(id: str, session: Session = Depends(get_session_dep)):
    return get_or_404(session, Domain, id, "Domain")


@router.put("/domains/{id}", response_model=DomainResponse)
def update_domain(id: str, req: DomainUpdate, session: Session = Depends(get_session_dep)):
    dm = get_or_404(session, Domain, id, "Domain")
    clash = session.scalar(
        select(Domain.id).where(
            Domain.workspace_id == dm.workspace_id, Domain.name == req.name, Domain.id != id
        )
    )
    if clash is not None:
        raise ValidationError(f"Domain já existe no workspace: {req.name}")
    dm.name = req.name
    if req.description is not None:
        dm.description = req.description
    session.commit()
    session.refresh(dm)
    return dm


@router.delete("/domains/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_domain(id: str, session: Session = Depends(get_session_dep)) -> Response:
    dm = get_or_404(session, Domain, id, "Domain")
    DomainService(session).delete(dm.workspace_id, dm.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/domains/{id}/stats", response_model=DomainStats)
def domain_stats(id: str, session: Session = Depends(get_session_dep)):
    get_or_404(session, Domain, id, "Domain")
    items = session.scalar(select(func.count()).select_from(Item).where(Item.domain_id == id))
    return DomainStats(items=items or 0)


@router.post("/domains/{id}/export")
def export_domain(
    id: str,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
) -> Response:
    dm = get_or_404(session, Domain, id, "Domain")
    data = ImportExportService(session, artifacts_dir).export_domain(dm.workspace_id, id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="domain-{dm.id}.zip"'},
    )
