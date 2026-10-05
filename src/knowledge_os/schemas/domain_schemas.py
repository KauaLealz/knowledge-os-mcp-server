"""Schemas Pydantic de Domain."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, RootModel


class DomainCreate(BaseModel):
    """Entrada para criação de domain."""

    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class DomainResponse(BaseModel):
    """Domain retornado pelas tools."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    description: str | None
    created_at: datetime | None
    updated_at: datetime | None


class DomainListResponse(RootModel[list[DomainResponse]]):
    """Lista de domains."""

    root: list[DomainResponse]
