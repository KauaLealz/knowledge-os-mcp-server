"""Peças comuns das rotas: o item de saída (com o scope herdado indicado) e a recusa de
parâmetro de consulta desconhecido (ex.: um filtro do modelo antigo, como `labels`)."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import Request

from knowledge_os.exceptions import ValidationError
from knowledge_os.schemas.item_schemas import ItemResponse
from knowledge_os.services.brain import Brain, Snapshot, is_expired
from knowledge_os.services.item_file import slugify
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


def scope_source(snap: Snapshot, record: ItemRecord) -> str | None:
    """De onde vem o scope efetivo de um item sem scope próprio: `subject`, `project` ou
    `workspace` (o primeiro explícito subindo a cadeia); None se o item define o seu ou se
    nada na cadeia define (vale o padrão `scoped`). `secret` nunca herda: sempre None."""
    if record.scope or record.type == "secret":
        return None
    ws_id, pj_id = slugify(record.workspace or ""), slugify(record.project or "")
    ws = snap.find_workspace(ws_id)
    pj = snap.find_project(ws_id, pj_id) if ws else None
    sj = snap.find_subject(ws_id, pj_id, record.subject) if (pj and record.subject) else None
    for level, node in (("subject", sj), ("project", pj), ("workspace", ws)):
        if node is not None and node.scope:
            return level
    return None


def chain_source(*levels: tuple[str, str | None]) -> str | None:
    """Para project/subject: o primeiro nível (do mais próximo ao workspace) com scope."""
    return next((name for name, scope in levels if scope), None)


def item_out(brain: Brain, record: ItemRecord) -> ItemResponse:
    """O item completo da API a partir do registro."""
    snap = brain.snapshot
    return ItemResponse.from_item(brain.view(record), scope_source(snap, record),
                                  is_expired(record))


def item_by_id(cid: str, item_id: str) -> ItemResponse:
    """Lê de novo (snapshot atual) e devolve o item; NotFoundError se não existe."""
    brain = Brain(cid)
    return item_out(brain, brain.snapshot.require(item_id))
