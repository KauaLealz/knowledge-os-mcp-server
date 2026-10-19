"""Peças comuns das rotas: o item de saída e a recusa de parâmetro de consulta desconhecido
(ex.: um filtro do modelo antigo, como `scope` ou `status`, que agora são tags)."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import Request

from knowledge_os.exceptions import ValidationError
from knowledge_os.schemas.item_schemas import ItemResponse
from knowledge_os.services.brain import Brain
from knowledge_os.storage.files import ItemRecord


def split(value: str | None) -> list[str] | None:
    """`"a,b"` → `["a", "b"]` (None se vazio)."""
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    return items or None


def check_query(request: Request, allowed: Iterable[str]) -> None:
    """422 com os válidos se a consulta traz um parâmetro que a rota não conhece: sem isso um
    filtro inexistente seria ignorado em silêncio e a lista pareceria filtrada."""
    valid = sorted(set(allowed))
    unknown = sorted(k for k in request.query_params if k not in valid)
    if unknown:
        raise ValidationError(
            f"Parâmetro(s) desconhecido(s): {', '.join(unknown)}. Válidos: {', '.join(valid)}"
        )


def item_out(brain: Brain, record: ItemRecord) -> ItemResponse:
    """O item completo da API a partir do registro."""
    return ItemResponse.from_item(brain.view(record))


def item_by_id(cid: str, item_id: str) -> ItemResponse:
    """Lê de novo (snapshot atual) e devolve o item; NotFoundError se não existe."""
    brain = Brain(cid)
    return item_out(brain, brain.snapshot.require(item_id))
