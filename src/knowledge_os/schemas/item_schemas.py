"""Schemas Pydantic v2 para as ferramentas de Item."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from knowledge_os.db.models import Item

ITEM_TYPES: tuple[str, ...] = (
    "context", "rule", "pattern", "procedure", "knowledge", "insight", "artifact",
    "secret",
)
MEMORY_CLASSES: tuple[str, ...] = ("ephemeral", "working", "longterm", "canonical")
ITEM_STATUSES: tuple[str, ...] = ("active", "done", "superseded", "deprecated")
# Chave estável: minúsculas, números e . _ / - (ex.: "regra/money-em-pagamentos").
KEY_PATTERN = r"^[a-z0-9][a-z0-9._/-]{0,199}$"


def decode_paths(raw: str | None) -> list[str]:
    """scope_paths é guardado como JSON; tolera vazio ou inválido."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _check_choice(value: str, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field} inválido: {value!r}. Use um de: {', '.join(allowed)}")
    return value


class ItemCreate(BaseModel):
    """Entrada de criação de item."""

    workspace_id: str
    project_id: str
    subject_id: str | None = None
    type: str
    memory_class: str = "longterm"  # sem aprovação: já vale; ephemeral = temporário
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    confidence: int | None = Field(default=None, ge=0, le=100)
    importance: int | None = Field(default=None, ge=0, le=10)
    ttl_days: int | None = Field(default=None, gt=0)
    key: str | None = Field(default=None, pattern=KEY_PATTERN)
    keywords: str | None = None
    source: str | None = Field(default=None, max_length=500)
    status: str = "active"
    scope_paths: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        return _check_choice(v, ITEM_TYPES, "type")

    @field_validator("memory_class")
    @classmethod
    def _memory_class(cls, v: str) -> str:
        return _check_choice(v, MEMORY_CLASSES, "memory_class")

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _check_choice(v, ITEM_STATUSES, "status")

    @model_validator(mode="after")
    def _ephemeral_requires_ttl(self) -> Self:
        if self.memory_class == "ephemeral" and self.ttl_days is None:
            raise ValueError("ttl_days é obrigatório para memory_class 'ephemeral'")
        return self


class ItemUpdate(BaseModel):
    """Entrada de atualização parcial de item (todos os campos opcionais)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    type: str | None = None
    summary: str | None = Field(default=None, min_length=1)
    content: str | None = Field(default=None, min_length=1)
    confidence: int | None = Field(default=None, ge=0, le=100)
    importance: int | None = Field(default=None, ge=0, le=10)
    ttl_days: int | None = Field(default=None, gt=0)
    keywords: str | None = None
    source: str | None = Field(default=None, max_length=500)
    status: str | None = None
    scope_paths: list[str] | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, v: str | None) -> str | None:
        return v if v is None else _check_choice(v, ITEM_TYPES, "type")

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        return v if v is None else _check_choice(v, ITEM_STATUSES, "status")


class ItemSearchRequest(BaseModel):
    """Parâmetros de busca FTS5."""

    workspace_id: str | None = None
    project_id: str | None = None
    subject_id: str | None = None
    query: str
    types: list[str] | None = None
    memory_classes: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=100)


class ItemSearchResult(BaseModel):
    """Resultado de busca: nunca inclui content."""

    id: str
    key: str | None = None
    type: str | None = None
    memory_class: str | None = None
    project: str | None = None
    subject: str | None = None
    title: str
    summary: str
    score: float
    uses: int = 0  # quantas vezes o item foi devolvido de propósito (busca, foco do contexto)


def _has_value(item: Item) -> bool:
    """`has_value` (EXISTS) expira só logo depois do INSERT, quando ainda não há valor."""
    from sqlalchemy import inspect

    if "has_value" in inspect(item).unloaded:
        return False
    return bool(item.has_value)


class ItemResponse(BaseModel):
    """Item completo, incluindo content."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    project_id: str
    subject_id: str | None = None
    type: str
    memory_class: str
    title: str
    summary: str
    content: str
    tags: list[str]
    labels: list[str]
    confidence: int | None
    importance: int | None
    ttl_days: int | None
    expires_at: datetime | None = None
    key: str | None = None
    keywords: str | None = None
    source: str | None = None
    status: str = "active"
    scope_paths: list[str] = []
    created_at: datetime | None
    updated_at: datetime | None
    last_accessed: datetime | None
    access_count: int
    has_value: bool | None = None  # só em `secret`: se o valor foi preenchido (nunca o valor)

    @classmethod
    def from_item(cls, item: Item) -> ItemResponse:
        """Converte um Item ORM (com tags/labels carregados) em resposta."""
        return cls(
            id=item.id,
            workspace_id=item.workspace_id,
            project_id=item.project_id,
            subject_id=item.subject_id,
            type=item.type,
            memory_class=item.memory_class,
            title=item.title,
            summary=item.summary,
            content=item.content,
            tags=sorted(t.name for t in item.tags),
            labels=sorted(lb.name for lb in item.labels),
            confidence=item.confidence,
            importance=item.importance,
            ttl_days=item.ttl_days,
            expires_at=item.expires_at,
            key=item.key,
            keywords=item.keywords,
            source=item.source,
            status=item.status or "active",
            scope_paths=decode_paths(item.scope_paths),
            created_at=item.created_at,
            updated_at=item.updated_at,
            last_accessed=item.last_accessed,
            access_count=item.access_count or 0,
            has_value=_has_value(item) if item.type == "secret" else None,
        )
