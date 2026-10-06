"""Schemas Pydantic de Project."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, RootModel


class ProjectCreate(BaseModel):
    """Entrada para criação de project."""

    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ProjectResponse(BaseModel):
    """Project retornado pelas tools."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    description: str | None
    created_at: datetime | None
    updated_at: datetime | None


class ProjectListResponse(RootModel[list[ProjectResponse]]):
    """Lista de projects."""

    root: list[ProjectResponse]
