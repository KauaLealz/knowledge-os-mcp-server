"""Schemas Pydantic para labels."""

from pydantic import BaseModel, ConfigDict, Field, RootModel


class LabelCreate(BaseModel):
    """Entrada de label_create."""

    name: str = Field(min_length=1, max_length=100)


class LabelResponse(BaseModel):
    """Label serializada."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str


class LabelListResponse(RootModel[list[LabelResponse]]):
    """Lista de labels."""
