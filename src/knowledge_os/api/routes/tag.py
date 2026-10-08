"""Rotas de tags e da associação item-tag (id da tag = o nome)."""

from fastapi import APIRouter, Depends, Response, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import ItemTagAdd, TagCreate
from knowledge_os.api.schemas.responses import TagResponse
from knowledge_os.services.brain import Brain, Tag
from knowledge_os.services.tag_service import TagService

router = APIRouter()


@router.get("/tags", response_model=list[TagResponse])
def list_tags(cid: str = Depends(get_connection_id)):
    return TagService(cid).list()


@router.post("/tags", status_code=status.HTTP_201_CREATED, response_model=TagResponse)
def create_tag(req: TagCreate, cid: str = Depends(get_connection_id)):
    return TagService(cid).create(req.name)


@router.delete("/tags/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(id: str, cid: str = Depends(get_connection_id)) -> Response:
    TagService(cid).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items/{id}/tags", response_model=list[TagResponse])
def item_tags(id: str, cid: str = Depends(get_connection_id)):
    record = Brain(cid).snapshot.require(id)
    return [Tag(n, n) for n in sorted(record.tags or [])]


@router.post(
    "/items/{id}/tags", status_code=status.HTTP_201_CREATED, response_model=list[TagResponse]
)
def add_item_tag(id: str, req: ItemTagAdd, cid: str = Depends(get_connection_id)):
    return TagService(cid).set_on_item(id, req.tag_id, True)


@router.delete("/items/{id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_tag(id: str, tag_id: str, cid: str = Depends(get_connection_id)) -> Response:
    TagService(cid).set_on_item(id, tag_id, False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
