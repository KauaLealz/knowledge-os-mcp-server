"""Schemas Pydantic de workspace (v6): nome e descrição (sem `scope` — o alcance vem da
hierarquia: um item no workspace vale para tudo abaixo)."""

from pydantic import BaseModel


class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    """`PUT /workspaces/{id}`: só o que vier muda (`name` renomeia)."""

    name: str | None = None
    description: str | None = None


class WorkspaceRow(BaseModel):
    """`WorkspaceService.rows()`."""

    id: str
    name: str
    description: str | None = None
    items: int
    projects: int
