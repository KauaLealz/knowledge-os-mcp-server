"""Modelos de entrada da API (reaproveita os schemas das tools MCP)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from knowledge_os.schemas.item_schemas import ItemCreate, ItemUpdate
from knowledge_os.schemas.label_schemas import LabelCreate
from knowledge_os.schemas.memory_schemas import MemoryClass
from knowledge_os.schemas.project_schemas import ProjectCreate
from knowledge_os.schemas.relation_schemas import RelationCreate
from knowledge_os.schemas.tag_schemas import TagCreate
from knowledge_os.schemas.workspace_schemas import WorkspaceCreate

__all__ = [
    "ConfidenceUpdate",
    "ConnectionUpdate",
    "ImportanceUpdate",
    "ItemCreate",
    "ItemLabelAdd",
    "ItemTagAdd",
    "ItemUpdate",
    "LabelCreate",
    "MemoryClassUpdate",
    "ProjectCreate",
    "ProjectUpdate",
    "RelationCreate",
    "TagCreate",
    "WorkspaceCreate",
    "WorkspaceUpdate",
]


class WorkspaceUpdate(BaseModel):
    """PUT /workspaces/{id}: name obrigatório; description só muda se informada."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ProjectUpdate(WorkspaceUpdate):
    """PUT /projects/{id}."""


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


class ConnectionUpdate(BaseModel):
    """PATCH: só o que vier muda."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    remote_url: str | None = None
    review_mode: Literal["direct", "pr"] | None = None
    enabled: bool | None = None
