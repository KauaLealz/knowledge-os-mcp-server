"""Rotas de labels e da associação item-label."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from src.api.deps import get_session_dep
from src.api.routes._helpers import get_or_404
from src.api.schemas.requests import ItemLabelAdd, LabelCreate
from src.api.schemas.responses import LabelResponse
from src.db.models import Item, Label
from src.services.label_service import LabelService

router = APIRouter()


@router.get("/labels", response_model=list[LabelResponse])
def list_labels(session: Session = Depends(get_session_dep)):
    return LabelService(session).list()


@router.post("/labels", status_code=status.HTTP_201_CREATED, response_model=LabelResponse)
def create_label(req: LabelCreate, session: Session = Depends(get_session_dep)):
    return LabelService(session).create(req.name)


@router.delete("/labels/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(id: str, session: Session = Depends(get_session_dep)) -> Response:
    LabelService(session).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items/{id}/labels", response_model=list[LabelResponse])
def item_labels(id: str, session: Session = Depends(get_session_dep)):
    item = get_or_404(session, Item, id, "Item")
    return sorted(item.labels, key=lambda lb: lb.name)


@router.post(
    "/items/{id}/labels", status_code=status.HTTP_201_CREATED, response_model=list[LabelResponse]
)
def add_item_label(id: str, req: ItemLabelAdd, session: Session = Depends(get_session_dep)):
    item = get_or_404(session, Item, id, "Item")
    label = get_or_404(session, Label, req.label_id, "Label")
    if label not in item.labels:
        item.labels.append(label)
        session.commit()
    return sorted(item.labels, key=lambda lb: lb.name)


@router.delete("/items/{id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_label(
    id: str, label_id: str, session: Session = Depends(get_session_dep)
) -> Response:
    item = get_or_404(session, Item, id, "Item")
    label = get_or_404(session, Label, label_id, "Label")
    if label in item.labels:
        item.labels.remove(label)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
