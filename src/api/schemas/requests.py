"""Modelos de entrada da API (reaproveita os schemas das tools MCP)."""

from pydantic import BaseModel, Field

from src.schemas.domain_schemas import DomainCreate
from src.schemas.item_schemas import ItemCreate, ItemUpdate
from src.schemas.label_schemas import LabelCreate
from src.schemas.memory_schemas import MemoryClass
from src.schemas.relation_schemas import RelationCreate
from src.schemas.tag_schemas import TagCreate
from src.schemas.workspace_schemas import WorkspaceCreate

__all__ = [
    "ConfidenceUpdate",
    "ConnectionCreate",
    "DomainCreate",
    "DomainUpdate",
    "ImportanceUpdate",
    "ItemCreate",
    "ItemLabelAdd",
    "ItemTagAdd",
    "ItemUpdate",
    "LabelCreate",
    "MemoryClassUpdate",
    "RelationCreate",
    "TagCreate",
    "WorkspaceCreate",
    "WorkspaceUpdate",
]


class WorkspaceUpdate(BaseModel):
    """PUT /workspaces/{id}: name obrigatório; description só muda se informada."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class DomainUpdate(WorkspaceUpdate):
    """PUT /domains/{id}."""


class ConfidenceUpdate(BaseModel):
    value: int = Field(ge=0, le=100)


class ImportanceUpdate(BaseModel):
    value: int = Field(ge=0, le=10)


class MemoryClassUpdate(BaseModel):
    memory_class: MemoryClass


class ItemTagAdd(BaseModel):
    tag_id: str = Field(min_length=1)


class ItemLabelAdd(BaseModel):
    label_id: str = Field(min_length=1)


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    db_type: str
    db_url: str = Field(min_length=1)
