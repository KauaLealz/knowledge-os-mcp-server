"""Schemas Pydantic de project e subject (v2): nome, descrição e `scope` explícito.

Mesma convenção de `scope` de `workspace_schemas`. Nas linhas, `scope_inherited_from` diz de
onde vem o `scope` efetivo quando o explícito falta (`project`/`workspace`; None se nada na
cadeia define e vale o padrão `scoped`).
"""

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    workspace_id: str
    name: str
    description: str | None = None
    scope: str | None = None


class ProjectUpdate(BaseModel):
    """`PUT /projects/{id}`: só o que vier muda (`name` renomeia)."""

    name: str | None = None
    description: str | None = None
    scope: str | None = None


class ProjectRow(BaseModel):
    """`ProjectService.rows()` + de onde vem o scope herdado."""

    id: str
    workspace_id: str
    name: str
    description: str | None = None
    scope: str
    scope_explicit: str | None = None
    scope_inherited_from: str | None = None
    items: int
    subjects: list[str]


class SubjectCreate(BaseModel):
    workspace_id: str
    project_id: str
    name: str
    description: str | None = None
    scope: str | None = None


class SubjectUpdate(ProjectUpdate):
    """`PUT /subjects/{id}`: só o que vier muda (`name` renomeia)."""


class SubjectRow(BaseModel):
    """`SubjectService.rows()` + o local e de onde vem o scope herdado."""

    id: str
    workspace_id: str
    project_id: str
    name: str
    description: str | None = None
    scope: str
    scope_explicit: str | None = None
    scope_inherited_from: str | None = None
    items: int
