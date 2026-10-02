"""Schemas Pydantic para tags."""

from pydantic import BaseModel, ConfigDict, Field, RootModel


class TagCreate(BaseModel):
    """Entrada de tag_create."""

    name: str = Field(min_length=1, max_length=100)


class TagResponse(BaseModel):
    """Tag serializada."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str


class TagListResponse(RootModel[list[TagResponse]]):
    """Lista de tags."""
