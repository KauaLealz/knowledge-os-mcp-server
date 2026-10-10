"""Grafo de relações a partir de itens de partida (`item_graph`).

Parte das `keys` (hop 0), segue as relações até `depth` saltos e devolve nós e arestas. Só
entram nós no alcance do repositório (`scope.distance`); relação para alvo que não se resolve é
ignorada. Em cada hop os vizinhos saem ordenados por sinais de uso (helped + opened) e depois
por `updated_at`; o `limit` conta nós vizinhos (não arestas) e, ao cortar, `truncated=true` e
`total_by_hop` traz o total real de vizinhos por hop antes do corte. Os nós devolvidos (exceto
os de entrada) contam como "abertos" no sinal de uso.
"""

from __future__ import annotations

from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import RELATION_TYPES, TYPES
from knowledge_os.services import scope
from knowledge_os.services.brain import Brain, Relation, Snapshot
from knowledge_os.storage.files import ItemRecord

MAX_KEYS = 5
MAX_DEPTH = 3
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DIRECTIONS = ("both", "out", "in")


def _check(keys: list[str], depth: int, limit: int, direction: str,
           relation_types: list[str] | None, types: list[str] | None) -> None:
    if not isinstance(keys, list) or not keys:
        raise ValidationError("keys deve ser uma lista com 1 a 5 keys (ou ids) de itens")
    if len(keys) > MAX_KEYS:
        raise ValidationError(f"no máximo {MAX_KEYS} keys por chamada (recebi {len(keys)})")
    if not 1 <= depth <= MAX_DEPTH:
        raise ValidationError(f"depth deve ir de 1 a {MAX_DEPTH} (recebi {depth})")
    if limit < 1:
        raise ValidationError("limit deve ser >= 1")
    if limit > MAX_LIMIT:
        raise ValidationError(f"limit máximo é {MAX_LIMIT} (recebi {limit}); use depth/filtros")
    if direction not in DIRECTIONS:
        raise ValidationError(
            f"direction inválida: {direction!r}. Válidas: {', '.join(DIRECTIONS)}")
    bad = [t for t in relation_types or [] if t not in RELATION_TYPES]
    if bad:
        raise ValidationError(
            f"relation_types inválido: {', '.join(bad)}. Válidos: {', '.join(RELATION_TYPES)}")
    bad = [t for t in types or [] if t not in TYPES]
    if bad:
        raise ValidationError(f"types inválido: {', '.join(bad)}. Válidos: {', '.join(TYPES)}")


class GraphService:
    """Consulta o grafo de relações da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def graph(
        self,
        keys: list[str],
        viewpoint: scope.Viewpoint = None,
        depth: int = 1,
        limit: int = DEFAULT_LIMIT,
        relation_types: list[str] | None = None,
        types: list[str] | None = None,
        direction: str = "both",
        everywhere: bool = False,
    ) -> dict[str, Any]:
        """Nós e arestas a até `depth` saltos das `keys`.

        Devolve `{nodes, edges, truncated, total_by_hop}`; os nós de entrada vêm com `hop: 0`.
        `types` filtra os vizinhos por tipo de item (e eles não são atravessados).
        `everywhere` ignora o alcance do `viewpoint` e usa tudo (a ficha do item na UI).
        """
        _check(keys, depth, limit, direction, relation_types, types)
        brain = Brain(self._connection_id)
        snap = brain.snapshot

        def reachable(record: ItemRecord) -> bool:
            return everywhere or scope.distance(snap, record, viewpoint) is not None

        starts: list[ItemRecord] = []
        for ref in keys:
            found = None
            if isinstance(ref, str):
                found = scope.resolve_key(snap, ref, viewpoint)
                if found is None and everywhere:
                    found = snap.get(ref)
            if found is None:
                raise NotFoundError(
                    f"Item '{ref}' não encontrado no alcance deste repositório. Confira a key "
                    "(item_search) ou use o id do item"
                )
            if found.id not in {s.id for s in starts}:
                starts.append(found)

        adjacency = self._adjacency(snap, relation_types, direction)
        type_filter = set(types or [])

        def neighbors(frontier: list[ItemRecord], seen: set[str]) -> list[ItemRecord]:
            found: dict[str, ItemRecord] = {}
            for node in frontier:
                for other_id in adjacency.get(node.id, ()):
                    other = snap.get(other_id)
                    if (other is None or other_id in seen or other_id in found
                            or (type_filter and other.type not in type_filter)
                            or not reachable(other)):
                        continue
                    found[other_id] = other
            return list(found.values())

        # Total real por hop: o grafo inteiro até `depth`, sem corte.
        total_by_hop: dict[str, int] = {}
        seen = {s.id for s in starts}
        frontier = starts
        for hop in range(1, depth + 1):
            frontier = neighbors(frontier, seen)
            if not frontier:
                break
            seen.update(r.id for r in frontier)
            total_by_hop[str(hop)] = len(frontier)

        usage = brain.usage()

        def rank(record: ItemRecord) -> tuple[int, float]:
            use = usage.get(record.id) or {}
            opened = use.get("opened", use.get("uses", 0))
            signal = int(use.get("helped", 0) or 0) + int(opened or 0)
            return (-signal, -record.updated_at.timestamp())

        # Seleção por hop até `limit`, só a partir dos nós já escolhidos (o grafo fica conexo).
        chosen: list[tuple[ItemRecord, int]] = [(s, 0) for s in starts]
        seen = {s.id for s in starts}
        frontier = starts
        budget = limit
        truncated = False
        for hop in range(1, depth + 1):
            candidates = sorted(neighbors(frontier, seen), key=rank)
            if len(candidates) > budget:
                truncated = True
                candidates = candidates[:budget]
            chosen.extend((r, hop) for r in candidates)
            seen.update(r.id for r in candidates)
            budget -= len(candidates)
            frontier = candidates
            if not frontier:
                break

        ids = {r.id for r, _hop in chosen}
        edges = [
            {"from": self._name(snap.get(rel.source_item_id)),
             "type": rel.relation_type,
             "to": self._name(snap.get(rel.target_item_id))}
            for rel in self._relations(snap, relation_types)
            if rel.source_item_id in ids and rel.target_item_id in ids
        ]
        start_ids = {s.id for s in starts}
        opened = [r.id for r, _hop in chosen if r.id not in start_ids]
        if opened:
            brain.track(opened)
        return {
            "nodes": [self._node(snap, r, hop) for r, hop in chosen],
            "edges": edges,
            "truncated": truncated,
            "total_by_hop": total_by_hop,
        }

    @staticmethod
    def _relations(snap: Snapshot, relation_types: list[str] | None) -> list[Relation]:
        wanted = set(relation_types or RELATION_TYPES)
        return [rel for rel in snap.relations() if rel.relation_type in wanted]

    @classmethod
    def _adjacency(cls, snap: Snapshot, relation_types: list[str] | None, direction: str,
                   ) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rel in cls._relations(snap, relation_types):
            if direction in ("both", "out"):
                out.setdefault(rel.source_item_id, []).append(rel.target_item_id)
            if direction in ("both", "in"):
                out.setdefault(rel.target_item_id, []).append(rel.source_item_id)
        return out

    @staticmethod
    def _name(record: ItemRecord | None) -> str | None:
        return (record.key or record.id) if record else None

    @staticmethod
    def _node(snap: Snapshot, record: ItemRecord, hop: int) -> dict[str, Any]:
        return {
            "key": record.key, "id": record.id, "type": record.type, "subtype": record.subtype,
            "title": record.title, "summary": record.summary,
            "scope": snap.effective_scope(record), "status": record.status or "active",
            "hop": hop,
        }
