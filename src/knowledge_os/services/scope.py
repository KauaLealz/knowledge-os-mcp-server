"""Alcance dos itens: o resolvedor único de "o que um repositório enxerga".

O item mora onde foi salvo (`<workspace>/<project>`); o alcance vem do scope efetivo
(`Snapshot.effective_scope`: item → subject → project → workspace, nada explícito = `scoped`).
Busca, pacote do hook, grafo, `item_get` e `item_save` usam só este módulo, para que a mesma
pergunta tenha a mesma resposta em todo lugar.

`viewpoint = (ws_id, pj_id)` (slugs) do repositório ligado, ou `None` para pasta não ligada.
A distância é o peso do item para quem olha:

- mesmo project → `1.0` (qualquer scope);
- outro project do mesmo workspace, com scope efetivo `workspace` ou `global` → `0.85`;
- outro workspace (ou pasta não ligada), com scope efetivo `global` → `0.7`;
- senão `None` (invisível).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from knowledge_os.services.item_file import slugify
from knowledge_os.storage.files import ItemRecord

if TYPE_CHECKING:
    from knowledge_os.services.brain import Snapshot

Viewpoint = tuple[str, str] | None

SAME_PROJECT = 1.0
SAME_WORKSPACE = 0.85
ELSEWHERE = 0.7


def _place(record: ItemRecord) -> tuple[str, str]:
    return slugify(record.workspace or ""), slugify(record.project or "")


def distance(snapshot: Snapshot, record: ItemRecord, viewpoint: Viewpoint) -> float | None:
    """Peso do item para quem olha de `viewpoint` (None: o item não está no alcance)."""
    ws_id, pj_id = _place(record)
    if viewpoint is not None and (ws_id, pj_id) == tuple(viewpoint):
        return SAME_PROJECT
    effective = snapshot.effective_scope(record)
    if viewpoint is not None and ws_id == viewpoint[0] and effective in ("workspace", "global"):
        return SAME_WORKSPACE
    if effective == "global":
        return ELSEWHERE
    return None


def reach(snapshot: Snapshot, viewpoint: Viewpoint) -> list[tuple[ItemRecord, float]]:
    """Itens no alcance de `viewpoint` com a distância, do mais perto ao mais longe (empate
    pelo path, para a ordem ser estável)."""
    found = []
    for record in snapshot.records.values():
        weight = distance(snapshot, record, viewpoint)
        if weight is not None:
            found.append((record, weight))
    found.sort(key=lambda pair: (-pair[1], pair[0].path))
    return found


def resolve_key(snapshot: Snapshot, key: str, viewpoint: Viewpoint) -> ItemRecord | None:
    """Item pela key na cadeia de alcance: o project do repositório primeiro, depois o resto
    do alcance (mais perto antes). Um `id` também resolve, em qualquer lugar: é único na
    conexão e quem o tem já sabe qual item quer."""
    by_id = snapshot.get(key)
    if by_id is not None:
        return by_id
    if viewpoint is not None:
        local = snapshot.by_key(viewpoint[0], viewpoint[1], key)
        if local is not None:
            return local
    for record, _weight in reach(snapshot, viewpoint):
        if record.key == key:
            return record
    return None


def where(record: ItemRecord) -> str:
    """Onde o item mora: `"<workspace>/<project>"` (os nomes, como no arquivo)."""
    return f"{record.workspace}/{record.project}"
