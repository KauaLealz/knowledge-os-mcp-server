"""Modelos de saída da API (reaproveita os schemas das tools MCP)."""

from datetime import datetime

from pydantic import BaseModel

from src.schemas.artifact_schemas import ArtifactResponse
from src.schemas.domain_schemas import DomainResponse
from src.schemas.item_schemas import ItemResponse, ItemSearchResult
from src.schemas.label_schemas import LabelResponse
from src.schemas.relation_schemas import RelationResponse
from src.schemas.tag_schemas import TagResponse
from src.schemas.workspace_schemas import WorkspaceResponse

__all__ = [
    "ArtifactResponse",
    "ConnectionResponse",
    "ConnectionTestResponse",
    "DomainResponse",
    "DomainStats",
    "ItemResponse",
    "ItemSearchResult",
    "LabelResponse",
    "RelationResponse",
    "SearchResponse",
    "TagResponse",
    "WorkspaceResponse",
    "WorkspaceStats",
]


class WorkspaceStats(BaseModel):
    domains: int
    items: int


class DomainStats(BaseModel):
    items: int


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[ItemSearchResult]


class ConnectionResponse(BaseModel):
    """Conexão sem senha (a URL sai mascarada)."""

    id: str
    name: str
    db_type: str
    url: str
    host: str | None
    port: int | None
    database: str | None
    username: str | None
    is_active: bool
    last_tested: datetime | None
    test_result: str | None
    created_at: datetime | None
    updated_at: datetime | None


class ConnectionTestResponse(BaseModel):
    status: str
    message: str | None = None
    latency_ms: int | None = None
