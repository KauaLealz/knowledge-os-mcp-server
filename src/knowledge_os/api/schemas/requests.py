"""Modelos de entrada da API (os de itens, relações, tags e organização vêm de `schemas/`)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from knowledge_os.schemas.item_schemas import FeedbackRequest, ItemCreate, ItemUpdate
from knowledge_os.schemas.project_schemas import (
    ProjectCreate,
    ProjectUpdate,
    SubjectCreate,
    SubjectUpdate,
)
from knowledge_os.schemas.relation_schemas import RelationBatch
from knowledge_os.schemas.tag_schemas import TagCreate, TagUpdate
from knowledge_os.schemas.workspace_schemas import WorkspaceCreate, WorkspaceUpdate

__all__ = [
    "ConnectionUpdate",
    "FeedbackRequest",
    "ItemCreate",
    "ItemUpdate",
    "ProjectCreate",
    "ProjectUpdate",
    "RelationBatch",
    "SubjectCreate",
    "SubjectUpdate",
    "TagCreate",
    "TagUpdate",
    "WorkspaceCreate",
    "WorkspaceUpdate",
]


class ConnectionUpdate(BaseModel):
    """PATCH: só o que vier muda."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    remote_url: str | None = None
    review_mode: Literal["direct", "pr"] | None = None
    enabled: bool | None = None
