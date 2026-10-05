"""Rotas de items (CRUD, busca FTS e ajustes de confidence/importance/memory_class)."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.api.deps import get_engine_dep, get_session_dep
from src.api.schemas.requests import (
    ConfidenceUpdate,
    ImportanceUpdate,
    ItemCreate,
    ItemUpdate,
    MemoryClassUpdate,
)
from src.api.schemas.responses import ItemResponse, SearchResponse
from src.db.models import Item
from src.services._common import tiebreak
from src.services.item_service import ItemService
from src.services.memory_service import MemoryService

router = APIRouter()


@router.get("/items", response_model=list[ItemResponse])
def list_items(
    workspace_id: str | None = None,
    domain_id: str | None = None,
    type: str | None = None,
    memory_class: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session_dep),
):
    stmt = select(Item)
    if workspace_id:
        stmt = stmt.where(Item.workspace_id == workspace_id)
    if domain_id:
        stmt = stmt.where(Item.domain_id == domain_id)
    if type:
        stmt = stmt.where(Item.type == type)
    if memory_class:
        stmt = stmt.where(Item.memory_class == memory_class)
    stmt = (
        stmt.order_by(Item.created_at, *tiebreak(session, "items")).limit(limit).offset(offset)
    )
    return [ItemResponse.from_item(i) for i in session.scalars(stmt)]


@router.post("/items", status_code=status.HTTP_201_CREATED, response_model=ItemResponse)
def create_item(req: ItemCreate, engine: Engine = Depends(get_engine_dep)):
    return ItemResponse.from_item(ItemService(engine).create(**req.model_dump()))


# Declarada antes de /items/{id} para "search" não ser lido como id.
@router.get("/items/search", response_model=SearchResponse)
def search_items(
    query: str,
    workspace_id: str,
    domain_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
    engine: Engine = Depends(get_engine_dep),
):
    service = ItemService(engine)
    ws_id = service.resolve_workspace_id(workspace_id)
    dm_id = service.resolve_domain_id(ws_id, domain_id) if domain_id else None
    results = service.search(ws_id, dm_id, query, limit=limit)
    return SearchResponse(query=query, total=len(results), results=results)


@router.get("/items/{id}", response_model=ItemResponse)
def get_item(id: str, engine: Engine = Depends(get_engine_dep)):
    return ItemResponse.from_item(ItemService(engine).get(id))


@router.put("/items/{id}", response_model=ItemResponse)
def update_item(id: str, req: ItemUpdate, engine: Engine = Depends(get_engine_dep)):
    fields = req.model_dump(exclude_unset=True)
    return ItemResponse.from_item(ItemService(engine).update(id, **fields))


@router.delete("/items/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(id: str, engine: Engine = Depends(get_engine_dep)) -> Response:
    ItemService(engine).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/items/{id}/confidence", response_model=ItemResponse)
def set_confidence(id: str, req: ConfidenceUpdate, engine: Engine = Depends(get_engine_dep)):
    return ItemResponse.from_item(ItemService(engine).update(id, confidence=req.value))


@router.put("/items/{id}/importance", response_model=ItemResponse)
def set_importance(id: str, req: ImportanceUpdate, engine: Engine = Depends(get_engine_dep)):
    return ItemResponse.from_item(ItemService(engine).update(id, importance=req.value))


@router.put("/items/{id}/memory_class", response_model=ItemResponse)
def set_memory_class(
    id: str, req: MemoryClassUpdate, session: Session = Depends(get_session_dep)
):
    item = MemoryService(session).promote(id, req.memory_class)
    return ItemResponse.from_item(item)
