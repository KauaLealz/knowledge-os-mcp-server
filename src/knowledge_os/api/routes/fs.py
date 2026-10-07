"""Navegação de pastas do filesystem local — só para escolher o `path` de uma connection
nova na UI. O servidor só escuta em 127.0.0.1 (ver `main.py`): mesmo limite de confiança
do próprio shell local, não um recurso exposto à rede.
"""

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.git_repo_service import GitRepoService

router = APIRouter()


class FsEntry(BaseModel):
    name: str
    path: str
    is_git_repo: bool


class FsBrowseResponse(BaseModel):
    path: str
    parent: str | None
    is_git_repo: bool
    entries: list[FsEntry]


@router.get("/fs/browse", response_model=FsBrowseResponse)
def browse(path: str | None = None) -> FsBrowseResponse:
    target = Path(path).expanduser() if path else Path.home()
    if not target.is_absolute():
        raise ValidationError(f"path deve ser absoluto: {path}")
    target = target.resolve()
    if not target.is_dir():
        raise ValidationError(f"path não é uma pasta existente: {target}")
    try:
        subdirs = sorted(
            (p for p in target.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except PermissionError:
        subdirs = []
    entries = [
        FsEntry(
            name=p.name,
            path=str(p),
            is_git_repo=GitRepoService(p).is_git_repo(),
        )
        for p in subdirs
    ]
    parent = str(target.parent) if target.parent != target else None
    return FsBrowseResponse(
        path=str(target),
        parent=parent,
        is_git_repo=GitRepoService(target).is_git_repo(),
        entries=entries,
    )
