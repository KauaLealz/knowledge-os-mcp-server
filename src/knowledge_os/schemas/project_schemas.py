"""Schemas Pydantic de project e subject (v6): nome e descrição (sem `scope` — o alcance vem
da hierarquia)."""

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    workspace_id: str
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    """`PUT /projects/{id}`: só o que vier muda (`name` renomeia)."""

    name: str | None = None
    description: str | None = None


class ProjectRow(BaseModel):
    """`ProjectService.rows()`."""

    id: str
    workspace_id: str
    name: str
    description: str | None = None
    items: int
    subjects: list[str]


class SubjectCreate(BaseModel):
    workspace_id: str
    project_id: str
    name: str
    description: str | None = None


class SubjectUpdate(ProjectUpdate):
    """`PUT /subjects/{id}`: só o que vier muda (`name` renomeia)."""


class SubjectRow(BaseModel):
    """`SubjectService.rows()` + o local."""

    id: str
    workspace_id: str
    project_id: str
    name: str
    description: str | None = None
    items: int
