"""Rotas de relações (v2): criar e apagar em lote pelo `RelationService` (`{source, type,
target}`, key ou id, atômico). Ler é pelo grafo (`GET /items/{id}/graph`)."""

from fastapi import APIRouter, Depends, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import RelationBatch
from knowledge_os.api.schemas.responses import RelationRow
from knowledge_os.services.relation_service import RelationService

router = APIRouter()


@router.post("/relations", status_code=status.HTTP_201_CREATED,
             response_model=list[RelationRow], response_model_exclude_none=True)
def create_relations(req: RelationBatch, cid: str = Depends(get_connection_id)):
    """`created` ou `unchanged` (já existia) por entrada; `supersedes` arquiva o alvo."""
    return RelationService(cid).create(req.items)


@router.delete("/relations", response_model=list[RelationRow], response_model_exclude_none=True)
def delete_relations(req: RelationBatch, cid: str = Depends(get_connection_id)):
    """`deleted` ou `missing` por entrada."""
    return RelationService(cid).delete(req.items)
