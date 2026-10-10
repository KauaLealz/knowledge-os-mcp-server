"""Modelos de saída da API (os de itens, tags e organização vêm de `schemas/`)."""

from datetime import datetime

from pydantic import BaseModel

from knowledge_os.schemas.item_schemas import ItemListResponse, ItemResponse, UtcDatetime
from knowledge_os.schemas.project_schemas import ProjectRow, SubjectRow
from knowledge_os.schemas.relation_schemas import RelationRow
from knowledge_os.schemas.tag_schemas import TagRow
from knowledge_os.schemas.workspace_schemas import WorkspaceRow

__all__ = [
    "ConnectionHealth",
    "ConnectionResponse",
    "ConnectionTest",
    "ConnectionTestResponse",
    "ItemListResponse",
    "ItemResponse",
    "ProjectRow",
    "RelationRow",
    "ScopeGraph",
    "SubjectRow",
    "TagRow",
    "TreeItem",
    "TreeProject",
    "TreeSubject",
    "WorkspaceRow",
    "WorkspaceTree",
]


class TreeItem(BaseModel):
    """Item na árvore da sidebar: o que a UI mostra sem abrir o item (`scope` = efetivo)."""

    id: str
    key: str | None
    title: str
    type: str
    subtype: str | None
    status: str
    scope: str
    updated_at: UtcDatetime | None
    expired: bool = False


class TreeSubject(BaseModel):
    id: str
    name: str
    description: str | None = None
    scope: str
    scope_explicit: str | None = None
    item_count: int
    items: list[TreeItem]


class TreeProject(BaseModel):
    id: str
    name: str
    description: str | None
    scope: str
    scope_explicit: str | None = None
    item_count: int
    items: list[TreeItem]
    subjects: list[TreeSubject] = []


class WorkspaceTree(BaseModel):
    projects: list[TreeProject]


class ScopeNode(BaseModel):
    """Nó do grafo de um escopo: o nó do `item_graph` (sem `hop`) + onde o item mora."""

    key: str | None
    id: str
    type: str
    subtype: str | None
    title: str
    summary: str
    scope: str
    status: str
    project_id: str
    project_name: str
    subject_id: str | None = None
    subject_name: str | None = None


class ScopeGraph(BaseModel):
    """Grafo de um escopo. Arestas como no `item_graph` (`{from, type, to}`), mas com os ids
    dos itens nas pontas: no grafo de um workspace a mesma key pode existir em dois projects."""

    nodes: list[ScopeNode]
    edges: list[dict[str, str]]


class ConnectionTest(BaseModel):
    status: str
    message: str | None = None
    latency_ms: int | None = None
    tested_at: datetime | None = None


class ConnectionResponse(BaseModel):
    """Conexão: um repositório git (clone local; `remote_url=None` = só local)."""

    id: str
    name: str
    path: str | None
    path_exists: bool = False
    is_git_repo: bool = False
    remote_url: str | None
    review_mode: str
    enabled: bool
    is_default: bool
    last_test: ConnectionTest | None
    created_at: datetime | None


class ConnectionTestResponse(BaseModel):
    status: str
    message: str | None = None
    latency_ms: int | None = None


class ParseError(BaseModel):
    path: str
    error: str


class ConnectionHealth(BaseModel):
    """`ConnectionService.health()`: a pasta, se é repositório git e os `.md` ignorados."""

    id: str
    name: str
    path: str
    ok: bool
    parse_errors: list[ParseError]
