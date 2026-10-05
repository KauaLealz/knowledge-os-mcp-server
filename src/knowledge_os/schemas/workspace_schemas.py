"""Schemas Pydantic de Workspace."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, RootModel


class WorkspaceCreate(BaseModel):
    """Entrada para criação de workspace."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class WorkspaceResponse(BaseModel):
    """Workspace retornado pelas tools."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime | None
    updated_at: datetime | None


class WorkspaceListResponse(RootModel[list[WorkspaceResponse]]):
    """Lista de workspaces."""

    root: list[WorkspaceResponse]
