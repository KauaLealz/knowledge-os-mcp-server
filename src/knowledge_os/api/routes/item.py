"""Rotas de itens (v2): listar com filtros, ler, criar, atualizar, apagar, busca explicada,
feedback, grafo do item e o valor de segredo.

Toda validação de conteúdo é do `ItemService` (que usa `model.validate_entry`): campo
desconhecido — inclusive os do modelo antigo, como `memory_class` — e valor fora da taxonomia
voltam 422 com a mensagem do serviço, que lista os válidos.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.routes._common import check_query, item_by_id, item_out, split
from knowledge_os.api.schemas.requests import FeedbackRequest, ItemCreate, ItemUpdate
from knowledge_os.api.schemas.responses import ItemListResponse, ItemResponse
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import EXPIRED, ORIGINS, SCOPES, SPEC_STATUSES, STATUSES, TYPES
from knowledge_os.services.brain import Brain, is_expired
from knowledge_os.services.graph import GraphService
from knowledge_os.services.item_file import slugify
from knowledge_os.services.item_service import MAX_LIMIT, ItemService
from knowledge_os.services.secret_service import SecretService

router = APIRouter()

SUBTYPES = tuple(dict.fromkeys(s for subs in TYPES.values() for s in subs))
_LIST_PARAMS = ("workspace_id", "project_id", "subject_id", "type", "subtype", "status",
                "scope", "origin", "tag", "limit", "offset")
_SEARCH_PARAMS = ("query", "workspace_id", "project_id", "subject_id", "types", "subtypes",
                  "status", "tags", "origin", "scope", "limit")
_GRAPH_PARAMS = ("depth", "limit", "relation_types", "types", "direction")
SEARCH_LIMIT = 50
CSV = "um valor, ou vários separados por vírgula"


def _choices(name: str, value: str | None, valid: tuple[str, ...]) -> set[str] | None:
    values = split(value)
    if values is None:
        return None
    bad = [v for v in values if v not in valid]
    if bad:
        raise ValidationError(f"{name} inválido: {', '.join(bad)}. Válidos: {', '.join(valid)}")
    return set(values)


def _require_place(cid: str, ws_id: str, pj_id: str, sj_id: str | None = None) -> None:
    """A UI cria e move itens só para lugares que existem (o serviço criaria os que faltam)."""
    snap = Brain(cid).snapshot
    ws = snap.workspace(ws_id)
    pj = snap.project(ws.id, pj_id)
    if sj_id:
        snap.subject(ws.id, pj.id, sj_id)


@router.get("/items", response_model=ItemListResponse)
def list_items(
    request: Request,
    workspace_id: str | None = None,
    project_id: str | None = Query(default=None, description=CSV),
    subject_id: str | None = Query(default=None, description=CSV),
    type: str | None = Query(default=None, description=CSV),
    subtype: str | None = Query(default=None, description=CSV),
    status: str | None = Query(default=None, description=f"{CSV}; expired = ttl vencido"),
    scope: str | None = Query(default=None, description=f"{CSV} (scope efetivo)"),
    origin: str | None = Query(default=None, description=CSV),
    tag: str | None = Query(default=None, description=f"{CSV}; o item precisa ter todas"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cid: str = Depends(get_connection_id),
):
    """Itens da conexão (todos os status, inclusive `archived`), mais antigos primeiro."""
    check_query(request, _LIST_PARAMS)
    types = _choices("type", type, tuple(TYPES))
    subtypes = _choices("subtype", subtype, SUBTYPES)
    statuses = _choices("status", status, STATUSES + SPEC_STATUSES + (EXPIRED,))
    scopes = _choices("scope", scope, SCOPES)
    origins = _choices("origin", origin, ORIGINS)
    tags = set(split(tag) or [])
    projects, subjects = split(project_id), split(subject_id)
    brain = Brain(cid)
    snap = brain.snapshot

    def wanted(r) -> bool:
        shown = EXPIRED if is_expired(r) else r.status
        return (
            (not workspace_id or slugify(r.workspace or "") == workspace_id)
            and (projects is None or slugify(r.project or "") in projects)
            and (subjects is None or bool(r.subject and slugify(r.subject) in subjects))
            and (types is None or r.type in types)
            and (subtypes is None or r.subtype in subtypes)
            and (statuses is None or shown in statuses)
            and (origins is None or r.origin in origins)
            and (scopes is None or snap.effective_scope(r) in scopes)
            and tags <= set(r.tags or [])
        )

    records = sorted((r for r in snap.records.values() if wanted(r)),
                     key=lambda r: (r.created_at, r.path))
    page = records[offset:offset + limit]
    return ItemListResponse(items=[item_out(brain, r) for r in page], total=len(records))


@router.post("/items", status_code=status.HTTP_201_CREATED, response_model=ItemResponse)
def create_item(req: ItemCreate, cid: str = Depends(get_connection_id)):
    fields = req.service_fields()
    ws, pj, sj = fields.pop("workspace"), fields.pop("project"), fields.pop("subject", None)
    _require_place(cid, ws, pj, sj)
    item = ItemService(cid).create(ws, pj, sj, **fields)
    return item_by_id(cid, item.id)


# Declarada antes de /items/{id} para "search" não ser lido como id.
@router.get("/items/search")
def search_items(
    request: Request,
    query: str = "",
    workspace_id: str | None = Query(default=None, description="sem ele, todos os workspaces"),
    project_id: str | None = Query(default=None, description=CSV),
    subject_id: str | None = Query(default=None, description=CSV),
    types: str | None = Query(default=None, description=CSV),
    subtypes: str | None = Query(default=None, description=CSV),
    status: str | None = Query(default=None, description=CSV),
    tags: str | None = Query(default=None, description=f"{CSV}; o item precisa ter todas"),
    origin: str | None = Query(default=None, description=CSV),
    scope: str | None = Query(default=None, description=f"{CSV} (scope efetivo)"),
    limit: int = Query(default=10, ge=1, le=SEARCH_LIMIT),
    cid: str = Depends(get_connection_id),
):
    """A resposta do `ItemService.search` (`{results: [...]}`, sem `content`), com
    `workspace_id`/`project_id`/`subject_id` em cada resultado para o link da UI.

    Com `workspace_id`: o workspace inteiro + os globais de fora; sem: tudo (`everywhere`).
    `project_id`/`subject_id` restringem os resultados a esses lugares.
    """
    check_query(request, _SEARCH_PARAMS)
    projects, subjects = split(project_id), split(subject_id)
    narrowed = projects is not None or subjects is not None
    service = ItemService(cid)
    out = service.search(
        query=query, workspace=workspace_id or None, everywhere=not workspace_id,
        types=split(types), subtypes=split(subtypes), status=split(status), tags=split(tags),
        origin=split(origin), scope=split(scope),
        # O serviço não filtra por project/subject: pede o máximo e corta aqui.
        limit=MAX_LIMIT if narrowed else limit,
    )
    snap = Brain(cid).snapshot
    results = []
    for row in out.get("results", []):
        record = snap.get(row["id"])
        if record is None:
            continue
        pj, sj = slugify(record.project or ""), slugify(record.subject) if record.subject else None
        if projects is not None and pj not in projects:
            continue
        if subjects is not None and sj not in subjects:
            continue
        results.append({**row, "workspace_id": slugify(record.workspace or ""),
                        "project_id": pj, "subject_id": sj})
    return {**out, "results": results[:limit]}


@router.get("/items/{id}", response_model=ItemResponse)
def get_item(id: str, cid: str = Depends(get_connection_id)):
    # Sem somar `opened`: o sinal de uso mede o agente, não quem navega pela UI.
    return item_by_id(cid, id)


def _update(id: str, req: ItemUpdate, cid: str) -> ItemResponse:
    record = Brain(cid).snapshot.require(id)
    fields = req.service_fields()
    if fields.get("workspace") or fields.get("project"):
        _require_place(cid, fields.get("workspace") or slugify(record.workspace or ""),
                       fields.get("project") or slugify(record.project or ""),
                       fields.get("subject"))
    elif fields.get("subject"):
        _require_place(cid, slugify(record.workspace or ""), slugify(record.project or ""),
                       fields["subject"])
    ItemService(cid).update(id, **fields)
    return item_by_id(cid, id)


@router.put("/items/{id}", response_model=ItemResponse)
def update_item(id: str, req: ItemUpdate, cid: str = Depends(get_connection_id)):
    """Atualização parcial (igual ao PATCH): só os campos enviados mudam."""
    return _update(id, req, cid)


@router.patch("/items/{id}", response_model=ItemResponse)
def patch_item(id: str, req: ItemUpdate, cid: str = Depends(get_connection_id)):
    return _update(id, req, cid)


@router.delete("/items/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(id: str, cid: str = Depends(get_connection_id)) -> Response:
    """Apaga o item e as relações que apontam para ele, num commit."""
    ItemService(cid).remove(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/items/{id}/feedback")
def item_feedback(id: str, req: FeedbackRequest, cid: str = Depends(get_connection_id)):
    """`ItemService.feedback` de um item: `helped`/`irrelevant` só contam; `wrong`/`outdated`
    põem em `review` (com a nota no conteúdo); `verified` grava `verified_at`."""
    result = ItemService(cid).feedback([{"id": id, **req.model_dump(exclude_unset=True)}])
    if result.get("missing"):
        raise NotFoundError(f"Item não encontrado: {id}")
    return result


@router.get("/items/{id}/graph")
def item_graph(
    request: Request,
    id: str,
    depth: int = 1,
    limit: int = 20,
    relation_types: str | None = Query(default=None, description=CSV),
    types: str | None = Query(default=None, description=CSV),
    direction: str = "both",
    cid: str = Depends(get_connection_id),
):
    """O `item_graph` a partir do item, sem limite de alcance (`everywhere`): `{nodes: [{key, id,
    type, subtype, title, summary, scope, status, hop}], edges: [{from, type, to}],
    truncated, total_by_hop}` (`from`/`to` = key, ou id quando o item não tem key)."""
    check_query(request, _GRAPH_PARAMS)
    record = Brain(cid).snapshot.require(id)
    viewpoint = (slugify(record.workspace or ""), slugify(record.project or ""))
    return GraphService(cid).graph(
        [id], viewpoint=viewpoint, depth=depth, limit=limit,
        relation_types=split(relation_types), types=split(types), direction=direction,
        everywhere=True,
    )


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
