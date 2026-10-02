"""Rotas de relations."""

from collections import defaultdict

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.api.auth import verify_token
from src.api.deps import get_session_dep
from src.api.routes._helpers import get_or_404
from src.api.schemas.requests import RelationCreate
from src.api.schemas.responses import RelationResponse
from src.db.models import Item, Relation
from src.services.relation_service import RelationService

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/relations", response_model=list[RelationResponse])
def list_relations(
    item_id: str | None = None,
    type: str | None = None,
    session: Session = Depends(get_session_dep),
):
    stmt = select(Relation).order_by(Relation.created_at, Relation.id)
    if item_id:
        stmt = stmt.where(
            or_(Relation.source_item_id == item_id, Relation.target_item_id == item_id)
        )
    if type:
        stmt = stmt.where(Relation.relation_type == type)
    return list(session.scalars(stmt))


@router.post("/relations", status_code=status.HTTP_201_CREATED, response_model=RelationResponse)
def create_relation(req: RelationCreate, session: Session = Depends(get_session_dep)):
    return RelationService(session).create(
        req.source_item_id, req.target_item_id, req.relation_type
    )


@router.delete("/relations/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_relation(id: str, session: Session = Depends(get_session_dep)) -> Response:
    RelationService(session).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items/{id}/relations", response_model=dict[str, list[RelationResponse]])
def item_relations(id: str, session: Session = Depends(get_session_dep)):
    get_or_404(session, Item, id, "Item")
    grouped: dict[str, list[Relation]] = defaultdict(list)
    for rel in RelationService(session).list(id):
        grouped[rel.relation_type].append(rel)
    return grouped
