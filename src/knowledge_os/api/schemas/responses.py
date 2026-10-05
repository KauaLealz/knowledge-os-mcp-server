"""Modelos de saída da API (reaproveita os schemas das tools MCP)."""

from datetime import datetime

from pydantic import BaseModel

from knowledge_os.schemas.artifact_schemas import ArtifactResponse
from knowledge_os.schemas.domain_schemas import DomainResponse
from knowledge_os.schemas.item_schemas import ItemResponse, ItemSearchResult
from knowledge_os.schemas.label_schemas import LabelResponse
from knowledge_os.schemas.relation_schemas import RelationResponse
from knowledge_os.schemas.tag_schemas import TagResponse
from knowledge_os.schemas.workspace_schemas import WorkspaceResponse

__all__ = [
    "ArtifactResponse",
    "ConnectionResponse",
    "ConnectionTest",
    "SchemaSyncResponse",
    "ConnectionTestResponse",
    "DomainResponse",
    "DomainStats",
    "ItemResponse",
    "ItemSearchResult",
    "LabelResponse",
    "RelationResponse",
    "SearchResponse",
    "TagResponse",
    "TreeDomain",
    "TreeItem",
    "WorkspaceResponse",
    "WorkspaceStats",
    "WorkspaceTree",
]


class WorkspaceStats(BaseModel):
    domains: int
    items: int


class TreeItem(BaseModel):
    id: str
    title: str
    type: str
    memory_class: str
    confidence: int | None
    updated_at: datetime | None


class TreeDomain(BaseModel):
    id: str
    name: str
    description: str | None
    item_count: int
    items: list[TreeItem]


class WorkspaceTree(BaseModel):
    domains: list[TreeDomain]


class DomainStats(BaseModel):
    items: int


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[ItemSearchResult]


class ConnectionTest(BaseModel):
    status: str
    message: str | None = None
    latency_ms: int | None = None
    tested_at: datetime | None = None


class ConnectionResponse(BaseModel):
    """Conexão sem senha: só `password_set` diz se existe uma (nunca qual)."""

    id: str
    name: str
    db_type: str
    path: str | None
    host: str | None
    port: int | None
    database: str | None
    username: str | None
    password_set: bool
    enabled: bool
    is_default: bool
    is_catalog: bool
    last_test: ConnectionTest | None
    created_at: datetime | None


class ConnectionTestResponse(BaseModel):
    status: str
    message: str | None = None
    latency_ms: int | None = None


class SchemaSyncResponse(BaseModel):
    connection_id: str
    status: str
    tables_created: list[str]
    columns_added: list[str]
    indexes_created: list[str]
    fts_created: bool
    pending_manual: list[str]
    version: str
    dry_run: bool
