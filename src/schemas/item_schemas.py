"""Schemas Pydantic v2 para as ferramentas de Item."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from src.db.models import Item

ITEM_TYPES: tuple[str, ...] = (
    "context", "rule", "pattern", "procedure", "knowledge", "insight", "artifact",
)
MEMORY_CLASSES: tuple[str, ...] = ("ephemeral", "working", "longterm", "canonical")


def _check_choice(value: str, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field} inválido: {value!r}. Use um de: {', '.join(allowed)}")
    return value


class ItemCreate(BaseModel):
    """Entrada de criação de item."""

    workspace_id: str
    domain_id: str
    type: str
    memory_class: str
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    confidence: int | None = Field(default=None, ge=0, le=100)
    importance: int | None = Field(default=None, ge=0, le=10)
    ttl_days: int | None = Field(default=None, gt=0)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        return _check_choice(v, ITEM_TYPES, "type")

    @field_validator("memory_class")
    @classmethod
    def _memory_class(cls, v: str) -> str:
        return _check_choice(v, MEMORY_CLASSES, "memory_class")

    @model_validator(mode="after")
    def _ephemeral_requires_ttl(self) -> Self:
        if self.memory_class == "ephemeral" and self.ttl_days is None:
            raise ValueError("ttl_days é obrigatório para memory_class 'ephemeral'")
        return self


class ItemUpdate(BaseModel):
    """Entrada de atualização parcial de item (todos os campos opcionais)."""

    summary: str | None = Field(default=None, min_length=1)
    content: str | None = Field(default=None, min_length=1)
    confidence: int | None = Field(default=None, ge=0, le=100)
    importance: int | None = Field(default=None, ge=0, le=10)
    ttl_days: int | None = Field(default=None, gt=0)


class ItemSearchRequest(BaseModel):
    """Parâmetros de busca FTS5."""

    workspace_id: str
    domain_id: str | None = None
    query: str
    types: list[str] | None = None
    memory_classes: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=100)


class ItemSearchResult(BaseModel):
    """Resultado de busca: nunca inclui content."""

    id: str
    title: str
    summary: str
    score: float


class ItemResponse(BaseModel):
    """Item completo, incluindo content."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    domain_id: str
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
    created_at: datetime | None
    updated_at: datetime | None
    last_accessed: datetime | None
    access_count: int

    @classmethod
    def from_item(cls, item: Item) -> ItemResponse:
        """Converte um Item ORM (com tags/labels carregados) em resposta."""
        return cls(
            id=item.id,
            workspace_id=item.workspace_id,
            domain_id=item.domain_id,
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
            created_at=item.created_at,
            updated_at=item.updated_at,
            last_accessed=item.last_accessed,
            access_count=item.access_count or 0,
        )
