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
    "ConnectionCreate",
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


class ConnectionCreate(BaseModel):
    """Corpo de criação: campos estruturados. `db_url`/`password_env` não existem (422)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    db_type: Literal["sqlite", "postgresql", "mysql"]
    path: str | None = None  # SQLite; relativo resolve contra o home
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = Field(default=None, repr=False)  # só escrita
    enabled: bool = True


class ConnectionUpdate(BaseModel):
    """PATCH: só o que vier muda. `password`: ausente mantém, valor substitui, null limpa."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    path: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = Field(default=None, min_length=1, repr=False)
    enabled: bool | None = None
