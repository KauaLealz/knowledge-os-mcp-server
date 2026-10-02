"""Schemas Pydantic para relações."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

RelationType = Literal[
    "related_to", "depends_on", "implements", "references", "supersedes", "derived_from"
]


class RelationCreate(BaseModel):
    """Entrada de relation_create."""

    source_item_id: str = Field(min_length=1)
    target_item_id: str = Field(min_length=1)
    relation_type: RelationType


class RelationResponse(BaseModel):
    """Relação serializada."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_item_id: str
    target_item_id: str
    relation_type: str
    created_at: datetime | None = None


class RelationListResponse(RootModel[list[RelationResponse]]):
    """Lista de relações."""
