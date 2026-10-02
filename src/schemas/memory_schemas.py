"""Schemas Pydantic para classes de memória."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryClass = Literal["ephemeral", "working", "longterm", "canonical"]


class MemoryPromoteRequest(BaseModel):
    """Entrada de memory_promote."""

    item_id: str = Field(min_length=1)
    target_memory: MemoryClass


class MemoryRenewRequest(BaseModel):
    """Entrada de memory_renew."""

    item_id: str = Field(min_length=1)
    ttl_days: int = Field(gt=0)


class MemoryResponse(BaseModel):
    """Estado de memória de um item."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_class: str
    ttl_days: int | None = None
    updated_at: datetime | None = None
