"""Rotas de items (CRUD, busca FTS e ajustes de confidence/importance/memory_class)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from knowledge_os.api.deps import get_engine_dep, get_session_dep
from knowledge_os.api.schemas.requests import (
    ConfidenceUpdate,
    ImportanceUpdate,
    ItemCreate,
    ItemUpdate,
    MemoryClassUpdate,
)
from knowledge_os.api.schemas.responses import ItemListResponse, ItemResponse, SearchResponse
from knowledge_os.db.models import Item
from knowledge_os.schemas.item_schemas import ITEM_TYPES, ItemSearchResult
from knowledge_os.services._common import tiebreak
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.memory_service import MemoryService
from knowledge_os.services.secret_service import SecretService

router = APIRouter()


@router.get("/items", response_model=ItemListResponse)
def list_items(
    workspace_id: str | None = None,
    project_id: str | None = None,
    subject_id: str | None = None,
    type: str | None = None,
    memory_class: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session_dep),
):
    filters = []
    if workspace_id:
        filters.append(Item.workspace_id == workspace_id)
    if project_id:
        filters.append(Item.project_id == project_id)
    if subject_id:
        filters.append(Item.subject_id == subject_id)
    if type:
        filters.append(Item.type == type)
    if memory_class:
        filters.append(Item.memory_class == memory_class)
    total = session.scalar(select(func.count()).select_from(Item).where(*filters)) or 0
    stmt = (
        select(Item)
        .where(*filters)
        .order_by(Item.created_at, *tiebreak(session, "items"))
        .limit(limit)
        .offset(offset)
    )
    items = [ItemResponse.from_item(i) for i in session.scalars(stmt)]
    return ItemListResponse(items=items, total=total)


@router.post("/items", status_code=status.HTTP_201_CREATED, response_model=ItemResponse)
def create_item(req: ItemCreate, engine: Engine = Depends(get_engine_dep)):
    return ItemResponse.from_item(ItemService(engine).create(**req.model_dump()))


class SearchHit(ItemSearchResult):
    """Resultado de busca com os ids necessários para montar o link na UI."""

    workspace_id: str | None = None
    project_id: str | None = None


class SearchHitsResponse(SearchResponse):
    results: list[SearchHit]  # type: ignore[assignment]


# Declarada antes de /items/{id} para "search" não ser lido como id.
@router.get("/items/search", response_model=SearchHitsResponse)
def search_items(
    query: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    types: str | None = Query(default=None, description="types separados por vírgula"),
    limit: int = Query(default=10, ge=1, le=50),
    engine: Engine = Depends(get_engine_dep),
    session: Session = Depends(get_session_dep),
):
    type_list = [t.strip() for t in types.split(",") if t.strip()] if types else None
    invalid = [t for t in type_list or [] if t not in ITEM_TYPES]
    if invalid:
        raise HTTPException(
            422,
            f"types inválidos: {', '.join(invalid)}. Válidos: {', '.join(ITEM_TYPES)}",
        )
    service = ItemService(engine)
    ws_id = service.resolve_workspace_id(workspace_id) if workspace_id else None
    pj_id = project_id
    if project_id and ws_id:
        pj_id = service.resolve_project_id(ws_id, project_id)
    rows = service.search(ws_id, pj_id, query, types=type_list or None, limit=limit)
    links = {}
    if rows:
        found = session.execute(
            select(Item.id, Item.workspace_id, Item.project_id).where(
                Item.id.in_([r["id"] for r in rows])
            )
        )
        links = {i: (w, d) for i, w, d in found}
    results = [
        SearchHit(**r, workspace_id=links.get(r["id"], (None, None))[0],
                  project_id=links.get(r["id"], (None, None))[1])
        for r in rows
    ]
    return SearchHitsResponse(query=query, total=len(results), results=results)


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


# Valor de segredo: entra só por aqui (o formulário da UI) e nenhuma rota o devolve. O corpo é
# lido à mão para que um erro de validação nunca ecoe o valor (o 422 padrão traz o `input`).
@router.put("/items/{id}/secret", status_code=status.HTTP_204_NO_CONTENT)
async def set_secret_value(
    id: str, request: Request, engine: Engine = Depends(get_engine_dep)
) -> Response:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, "Corpo deve ser JSON: {\"value\": \"...\"}") from None
    value = body.get("value") if isinstance(body, dict) else None
    if not isinstance(value, str) or not value:
        raise HTTPException(422, "Informe value (texto não vazio)")
    # keyring e retry do SQLite bloqueiam: fora do event loop da UI
    await run_in_threadpool(SecretService(engine).set_value, id, value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/items/{id}/secret", status_code=status.HTTP_204_NO_CONTENT)
def clear_secret_value(id: str, engine: Engine = Depends(get_engine_dep)) -> Response:
    SecretService(engine).clear_value(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
