"""Rotas de tags gerenciadas (v2): lista com contagem, criar, renomear (mescla se o novo nome
já existe) e apagar com prévia (`confirm=true` aplica). A tag de um item muda pelo item."""

from fastapi import APIRouter, Depends, status

from knowledge_os.api.deps import get_connection_id
from knowledge_os.api.schemas.requests import TagCreate, TagUpdate
from knowledge_os.api.schemas.responses import TagRow
from knowledge_os.services.tag_service import TagService

router = APIRouter()


@router.get("/tags", response_model=list[TagRow])
def list_tags(cid: str = Depends(get_connection_id)):
    """`[{name, count}]` por nome; inclui as do vocabulário sem item (`count: 0`)."""
    return TagService(cid).list()


@router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tags(req: TagCreate, cid: str = Depends(get_connection_id)):
    """`{created, existing}` com os nomes já normalizados (kebab-case)."""
    return TagService(cid).create(req.names)


@router.put("/tags/{name}")
def update_tag(name: str, req: TagUpdate, cid: str = Depends(get_connection_id)):
    """Renomeia em todos os itens e no vocabulário: `{renamed, merged}`."""
    return TagService(cid).update(name, req.new_name)


@router.delete("/tags/{name}")
def delete_tag(name: str, confirm: bool = False, cid: str = Depends(get_connection_id)):
    """Sem `confirm`: `{status: "preview", tags: [{name, items}]}`; com: remove dos itens."""
    return TagService(cid).delete([name], confirm=confirm)
