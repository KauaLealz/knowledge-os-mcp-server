"""Schemas Pydantic de relações (v2): o lote do `RelationService` (`{source, type, target}`).

`source`/`target` são key ou id; o tipo é validado pelo serviço (que lista os válidos).
"""

from typing import Any

from pydantic import BaseModel


class RelationBatch(BaseModel):
    """Corpo de `POST /relations` e `DELETE /relations`: até 20 entradas, atômico."""

    items: list[dict[str, Any]]


class RelationRow(BaseModel):
    """Resultado por entrada: `created|unchanged` (criar) ou `deleted|missing` (apagar)."""

    index: int
    source: str
    type: str
    target: str
    action: str
    status: str | None = None  # em modo PR
    pr_url: str | None = None
    issue_url: str | None = None
