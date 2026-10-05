"""Rotas de tags e da associação item-tag."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from knowledge_os.api.deps import get_session_dep
from knowledge_os.api.routes._helpers import get_or_404
from knowledge_os.api.schemas.requests import ItemTagAdd, TagCreate
from knowledge_os.api.schemas.responses import TagResponse
from knowledge_os.db.models import Item, Tag
from knowledge_os.services.tag_service import TagService

router = APIRouter()


@router.get("/tags", response_model=list[TagResponse])
def list_tags(session: Session = Depends(get_session_dep)):
    return TagService(session).list()


@router.post("/tags", status_code=status.HTTP_201_CREATED, response_model=TagResponse)
def create_tag(req: TagCreate, session: Session = Depends(get_session_dep)):
    return TagService(session).create(req.name)


@router.delete("/tags/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(id: str, session: Session = Depends(get_session_dep)) -> Response:
    TagService(session).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items/{id}/tags", response_model=list[TagResponse])
def item_tags(id: str, session: Session = Depends(get_session_dep)):
    item = get_or_404(session, Item, id, "Item")
    return sorted(item.tags, key=lambda t: t.name)


@router.post(
    "/items/{id}/tags", status_code=status.HTTP_201_CREATED, response_model=list[TagResponse]
)
def add_item_tag(id: str, req: ItemTagAdd, session: Session = Depends(get_session_dep)):
    item = get_or_404(session, Item, id, "Item")
    tag = get_or_404(session, Tag, req.tag_id, "Tag")
    if tag not in item.tags:
        item.tags.append(tag)
        session.commit()
    return sorted(item.tags, key=lambda t: t.name)


@router.delete("/items/{id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_tag(id: str, tag_id: str, session: Session = Depends(get_session_dep)) -> Response:
    item = get_or_404(session, Item, id, "Item")
    tag = get_or_404(session, Tag, tag_id, "Tag")
    if tag in item.tags:
        item.tags.remove(tag)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
