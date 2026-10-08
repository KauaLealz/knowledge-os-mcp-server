"""Rotas de relations (guardadas no frontmatter do item de origem)."""

from collections import defaultdict

from fastapi import APIRouter, Depends, Response, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import RelationCreate
from knowledge_os.api.schemas.responses import RelationResponse
from knowledge_os.services.brain import Brain, Relation
from knowledge_os.services.relation_service import RelationService

router = APIRouter()


@router.get("/relations", response_model=list[RelationResponse])
def list_relations(
    item_id: str | None = None,
    type: str | None = None,
    cid: str = Depends(get_connection_id),
):
    return RelationService(cid).list_all(item_id, type)


@router.post("/relations", status_code=status.HTTP_201_CREATED, response_model=RelationResponse)
def create_relation(req: RelationCreate, cid: str = Depends(get_connection_id)):
    return RelationService(cid).create(req.source_item_id, req.target_item_id, req.relation_type)


@router.delete("/relations/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_relation(id: str, cid: str = Depends(get_connection_id)) -> Response:
    RelationService(cid).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items/{id}/relations", response_model=dict[str, list[RelationResponse]])
def item_relations(id: str, cid: str = Depends(get_connection_id)):
    snap = Brain(cid).snapshot
    snap.require(id)
    grouped: dict[str, list[Relation]] = defaultdict(list)
    for rel in snap.relations():
        if id in (rel.source_item_id, rel.target_item_id):
            grouped[rel.relation_type].append(rel)
    return grouped
