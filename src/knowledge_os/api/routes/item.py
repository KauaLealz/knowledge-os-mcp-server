"""Rotas de items (CRUD, busca e ajustes de confidence/importance/memory_class)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import (
    ConfidenceUpdate,
    ImportanceUpdate,
    ItemCreate,
    ItemUpdate,
    MemoryClassUpdate,
)
from knowledge_os.api.schemas.responses import ItemListResponse, ItemResponse, SearchResponse
from knowledge_os.schemas.item_schemas import ITEM_TYPES, ItemSearchResult
from knowledge_os.services.brain import Brain
from knowledge_os.services.item_file import slugify
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.memory_service import MemoryService
from knowledge_os.services.secret_service import SecretService

router = APIRouter()


def _split(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


@router.get("/items", response_model=ItemListResponse)
def list_items(
    workspace_id: str | None = None,
    project_id: str | None = Query(
        default=None, description="um id, ou vários separados por vírgula"
    ),
    subject_id: str | None = Query(
        default=None, description="um id, ou vários separados por vírgula"
    ),
    type: str | None = None,
    memory_class: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cid: str = Depends(get_connection_id),
):
    brain = Brain(cid)
    projects, subjects = _split(project_id), _split(subject_id)
    records = [
        r for r in brain.snapshot.records.values()
        if (not workspace_id or slugify(r.workspace or "") == workspace_id)
        and (projects is None or slugify(r.project or "") in projects)
        and (subjects is None or (r.subject and slugify(r.subject) in subjects))
        and (not type or r.type == type)
        and (not memory_class or r.memory_class == memory_class)
    ]
    records.sort(key=lambda r: (r.created_at, r.path))
    page = records[offset:offset + limit]
    return ItemListResponse(
        items=[ItemResponse.from_item(i) for i in brain.views(page)], total=len(records)
    )


@router.post("/items", status_code=status.HTTP_201_CREATED, response_model=ItemResponse)
def create_item(req: ItemCreate, cid: str = Depends(get_connection_id)):
    return ItemResponse.from_item(ItemService(cid).create(**req.model_dump()))


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
    project_id: str | None = Query(
        default=None, description="um id, ou vários separados por vírgula"
    ),
    subject_id: str | None = Query(
        default=None, description="um id, ou vários separados por vírgula"
    ),
    types: str | None = Query(default=None, description="types separados por vírgula"),
    tags: str | None = Query(
        default=None, description="tags separadas por vírgula; o item precisa ter todas"
    ),
    labels: str | None = Query(
        default=None, description="labels separados por vírgula; o item precisa ter todos"
    ),
    limit: int = Query(default=10, ge=1, le=50),
    cid: str = Depends(get_connection_id),
):
    type_list = [t.strip() for t in types.split(",") if t.strip()] if types else None
    invalid = [t for t in type_list or [] if t not in ITEM_TYPES]
    if invalid:
        raise HTTPException(
            422,
            f"types inválidos: {', '.join(invalid)}. Válidos: {', '.join(ITEM_TYPES)}",
        )
    service = ItemService(cid)
    ws_id = service.resolve_workspace_id(workspace_id) if workspace_id else None
    # `project_id` aceita vários ids separados por vírgula — resolve_project_id (nomes
    # amigáveis) só faz sentido pra um id só, então só tenta resolver nesse caso.
    pj_ids = _split(project_id)
    if pj_ids and len(pj_ids) == 1 and ws_id:
        pj_ids = [service.resolve_project_id(ws_id, pj_ids[0])]
    rows = service.search(
        ws_id, pj_ids, query, subject_id=_split(subject_id), types=type_list or None,
        limit=limit, tags=_split(tags), labels=_split(labels),
    )
    results = [SearchHit(**r) for r in rows]
    return SearchHitsResponse(query=query, total=len(results), results=results)


@router.get("/items/{id}", response_model=ItemResponse)
def get_item(id: str, cid: str = Depends(get_connection_id)):
    return ItemResponse.from_item(ItemService(cid).get(id))


@router.put("/items/{id}", response_model=ItemResponse)
def update_item(id: str, req: ItemUpdate, cid: str = Depends(get_connection_id)):
    fields = req.model_dump(exclude_unset=True)
    return ItemResponse.from_item(ItemService(cid).update(id, **fields))


@router.delete("/items/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(id: str, cid: str = Depends(get_connection_id)) -> Response:
    ItemService(cid).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/items/{id}/confidence", response_model=ItemResponse)
def set_confidence(id: str, req: ConfidenceUpdate, cid: str = Depends(get_connection_id)):
    return ItemResponse.from_item(ItemService(cid).update(id, confidence=req.value))


@router.put("/items/{id}/importance", response_model=ItemResponse)
def set_importance(id: str, req: ImportanceUpdate, cid: str = Depends(get_connection_id)):
    return ItemResponse.from_item(ItemService(cid).update(id, importance=req.value))


@router.put("/items/{id}/memory_class", response_model=ItemResponse)
def set_memory_class(id: str, req: MemoryClassUpdate, cid: str = Depends(get_connection_id)):
    item = MemoryService(cid).promote(id, req.memory_class)
    return ItemResponse.from_item(item)


# Valor de segredo: entra só por aqui (o formulário da UI) e nenhuma rota o devolve. O corpo é
# lido à mão para que um erro de validação nunca ecoe o valor (o 422 padrão traz o `input`).
@router.put("/items/{id}/secret", status_code=status.HTTP_204_NO_CONTENT)
async def set_secret_value(
    id: str, request: Request, cid: str = Depends(get_connection_id)
) -> Response:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, 'Corpo deve ser JSON: {"value": "..."}') from None
    value = body.get("value") if isinstance(body, dict) else None
    if not isinstance(value, str) or not value:
        raise HTTPException(422, "Informe value (texto não vazio)")
    # keyring e escrita em disco bloqueiam: fora do event loop da UI
    await run_in_threadpool(SecretService(cid).set_value, id, value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/items/{id}/secret", status_code=status.HTTP_204_NO_CONTENT)
def clear_secret_value(id: str, cid: str = Depends(get_connection_id)) -> Response:
    SecretService(cid).clear_value(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
