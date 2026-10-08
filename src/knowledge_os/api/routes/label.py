"""Rotas de labels e da associação item-label (id do label = o nome)."""

from fastapi import APIRouter, Depends, Response, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import ItemLabelAdd, LabelCreate
from knowledge_os.api.schemas.responses import LabelResponse
from knowledge_os.services.brain import Brain, Label
from knowledge_os.services.label_service import LabelService

router = APIRouter()


@router.get("/labels", response_model=list[LabelResponse])
def list_labels(cid: str = Depends(get_connection_id)):
    return LabelService(cid).list()


@router.post("/labels", status_code=status.HTTP_201_CREATED, response_model=LabelResponse)
def create_label(req: LabelCreate, cid: str = Depends(get_connection_id)):
    return LabelService(cid).create(req.name)


@router.delete("/labels/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(id: str, cid: str = Depends(get_connection_id)) -> Response:
    LabelService(cid).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items/{id}/labels", response_model=list[LabelResponse])
def item_labels(id: str, cid: str = Depends(get_connection_id)):
    record = Brain(cid).snapshot.require(id)
    return [Label(n, n) for n in sorted(record.labels or [])]


@router.post(
    "/items/{id}/labels", status_code=status.HTTP_201_CREATED, response_model=list[LabelResponse]
)
def add_item_label(id: str, req: ItemLabelAdd, cid: str = Depends(get_connection_id)):
    return LabelService(cid).set_on_item(id, req.label_id, True)


@router.delete("/items/{id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_label(id: str, label_id: str, cid: str = Depends(get_connection_id)) -> Response:
    LabelService(cid).set_on_item(id, label_id, False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
