"""Schemas Pydantic de workspace (v2): nome, descrição e `scope` explícito.

`scope` segue a convenção dos serviços: ausente/None = não define (create) ou não muda
(update); um de `model.SCOPES` = grava explícito; `""` (só no update) = volta a herdar. O
serviço valida e lista os valores válidos.
"""

from pydantic import BaseModel


class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None
    scope: str | None = None


class WorkspaceUpdate(BaseModel):
    """`PUT /workspaces/{id}`: só o que vier muda (`name` renomeia)."""

    name: str | None = None
    description: str | None = None
    scope: str | None = None


class WorkspaceRow(BaseModel):
    """`WorkspaceService.rows()`: `scope` = o que vale; `scope_explicit` = o gravado."""

    id: str
    name: str
    description: str | None = None
    scope: str
    scope_explicit: str | None = None
    items: int
    projects: int
