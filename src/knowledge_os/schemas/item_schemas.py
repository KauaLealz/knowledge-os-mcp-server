"""Schemas Pydantic de item (v2): entrada fina para o `ItemService` e o item completo de saída.

Entrada: `ItemCreate`/`ItemUpdate` aceitam campo extra e não validam valores — o
`ItemService.save` (via `model.validate_entry`) recusa campo desconhecido (ex.: `memory_class`)
e valor fora da taxonomia com a lista dos válidos. O local vem por id
(`workspace_id`/`project_id`/`subject_id`) e vira `workspace`/`project`/`subject` do serviço.

Saída: `ItemResponse` traz o `scope` explícito do item, o `effective_scope` (o que vale, com a
herança subject → project → workspace) e `scope_inherited_from` (de onde veio o efetivo quando
o item não define o seu: `subject`, `project`, `workspace`, ou None se nada na cadeia define).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from knowledge_os.services.brain import Item

LOCATION_IDS = {"workspace_id": "workspace", "project_id": "project", "subject_id": "subject"}


class _Entry(BaseModel):
    """Corpo livre: campos conhecidos documentados; o resto vai ao serviço, que valida."""

    model_config = ConfigDict(extra="allow")

    def service_fields(self) -> dict[str, Any]:
        """Os campos enviados (só os presentes), com o local traduzido para o serviço."""
        data = self.model_dump(exclude_unset=True)
        return {LOCATION_IDS.get(k, k): v for k, v in data.items()}


class ItemCreate(_Entry):
    """Entrada de criação: `type`, `title` e `summary` obrigatórios (cobrados pelo serviço)."""

    workspace_id: str
    project_id: str
    subject_id: str | None = None
    key: str | None = None
    type: str | None = None
    subtype: str | None = None
    scope: str | None = None
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    links: list[dict[str, Any]] | None = None
    scope_paths: list[str] | None = None
    ttl_days: int | None = None
    keywords: str | None = None
    source: str | None = None
    origin: str | None = None


class ItemUpdate(_Entry):
    """Atualização parcial: só o que vier muda (tags e links substituem os atuais).

    `scope: null` tira o explícito (o item volta a herdar); `subject_id: null` tira o subject;
    `workspace_id` + `project_id` juntos movem o item.
    """

    workspace_id: str | None = None
    project_id: str | None = None
    subject_id: str | None = None
    type: str | None = None
    subtype: str | None = None
    scope: str | None = None
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    links: list[dict[str, Any]] | None = None
    scope_paths: list[str] | None = None
    ttl_days: int | None = None
    keywords: str | None = None
    source: str | None = None
    origin: str | None = None


class FeedbackRequest(_Entry):
    """`POST /items/{id}/feedback`: o que o item fez (`outcome`, ver `model.OUTCOMES`)."""

    outcome: str
    note: str | None = None
    query: str | None = None


class ItemResponse(BaseModel):
    """Item completo (com `content`); nunca o valor de um segredo (só `has_value`)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str | None = None
    workspace_id: str
    project_id: str
    subject_id: str | None = None
    workspace: str
    project: str
    subject: str | None = None
    where: str
    type: str
    subtype: str | None = None
    scope: str | None = None
    effective_scope: str
    scope_inherited_from: str | None = None
    title: str
    summary: str
    content: str
    status: str
    expired: bool = False
    tags: list[str]
    links: list[dict[str, str]]
    scope_paths: list[str] = []
    ttl_days: int | None = None
    expires_at: datetime | None = None
    keywords: str | None = None
    source: str | None = None
    origin: str
    verified_at: datetime | None = None
    verified_commit: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_accessed: datetime | None = None
    access_count: int = 0
    has_value: bool | None = None  # só em `secret`: se o valor foi preenchido (nunca o valor)

    @classmethod
    def from_item(cls, item: Item, inherited_from: str | None = None,
                  expired: bool = False) -> ItemResponse:
        """Converte um item dos services (`brain.Item`) em resposta."""
        return cls(
            id=item.id, key=item.key, workspace_id=item.workspace_id,
            project_id=item.project_id, subject_id=item.subject_id, workspace=item.workspace,
            project=item.project, subject=item.subject,
            where=f"{item.workspace}/{item.project}", type=item.type, subtype=item.subtype,
            scope=item.scope, effective_scope=item.effective_scope,
            scope_inherited_from=None if item.scope else inherited_from, title=item.title,
            summary=item.summary, content=item.content, status=item.status or "active",
            expired=expired, tags=sorted(item.tags), links=[dict(lk) for lk in item.links],
            scope_paths=list(item.scope_paths), ttl_days=item.ttl_days,
            expires_at=item.expires_at, keywords=item.keywords, source=item.source,
            origin=item.origin, verified_at=item.verified_at,
            verified_commit=item.verified_commit, created_at=item.created_at,
            updated_at=item.updated_at, last_accessed=item.last_accessed,
            access_count=item.access_count or 0,
            has_value=bool(item.has_value) if item.type == "secret" else None,
        )


class ItemListResponse(BaseModel):
    """Página de `GET /items`: os itens da página + o total real (antes de limit/offset)."""

    items: list[ItemResponse]
    total: int
