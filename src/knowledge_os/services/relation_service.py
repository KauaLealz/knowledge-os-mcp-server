"""Relation service: ligações item→item, guardadas nos `links` da origem (v6).

`create`/`delete` trabalham em lote (até 20 entradas `{source, type, target}`), atômicos: toda
entrada é resolvida e validada antes de qualquer mudança, e o lote vira uma publicação só.
`source`/`target` são key ou id, resolvidos dentro da conexão. Tipos de relação: `depends_on`,
`relates_to` (`model.LINK_RELATIONS`). Não há `supersedes` — para aposentar um item, ajuste-o
ou apague-o.
"""

from __future__ import annotations

import logging
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import LINK_RELATIONS
from knowledge_os.services.brain import Brain, Draft, Relation
from knowledge_os.services.git_repo_service import PublishResult
from knowledge_os.storage.files import ItemRecord

logger = logging.getLogger(__name__)

MAX_BATCH = 20

__all__ = ["LINK_RELATIONS", "RelationService", "review_fields"]


def review_fields(result: PublishResult | None) -> dict[str, Any]:
    """Em modo PR a mudança só vale após o merge: o que o chamador precisa para avisar. O
    `status` aqui é o da PUBLICAÇÃO (pending_review/issue_opened), não um campo de item."""
    if result is None or result.status == "published":
        return {}
    out: dict[str, Any] = {"status": result.status}
    if result.pr_url:
        out["pr_url"] = result.pr_url
    if result.issue_url:
        out["issue_url"] = result.issue_url
    return out


def _entries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValidationError(
            'items deve ser uma lista não vazia de {"source": key|id, "type": ..., "target": '
            f"key|id}}. Tipos: {', '.join(LINK_RELATIONS)}"
        )
    if len(items) > MAX_BATCH:
        raise ValidationError(f"no máximo {MAX_BATCH} relações por chamada (recebi {len(items)})")
    return items


def _resolve_ref(draft: Draft, ref: str) -> ItemRecord | None:
    """Resolve uma referência (id ou key) a um item da conexão. Por id primeiro; senão o
    primeiro item cuja key bate (keys seguem `<tipo>/<nome>`, em geral únicas no project)."""
    found = draft.records.get(ref)
    if found is not None:
        return found
    for record in draft.records.values():
        if record.key == ref:
            return record
    return None


def _resolve(draft: Draft, ref: Any, index: int, role: str) -> ItemRecord | None:
    if not isinstance(ref, str) or not ref.strip():
        raise ValidationError(f"items[{index}]: '{role}' deve ser a key ou o id de um item")
    return _resolve_ref(draft, ref.strip())


def _not_found(index: int, role: str, ref: str) -> NotFoundError:
    return NotFoundError(
        f"items[{index}]: {role} '{ref}' não existe nesta conexão. Confira a key (item_search) "
        "ou use o id do item"
    )


class RelationService:
    """Operações sobre ligações item→item da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    @staticmethod
    def _plan(draft: Draft, items: Any, *, strict: bool,
              ) -> list[tuple[int, str, ItemRecord | None, ItemRecord | None]]:
        """Valida o lote inteiro e resolve as pontas: (índice, tipo, origem, alvo).
        `strict` (criar): ponta inexistente é erro; senão fica None (remover → `missing`)."""
        plan = []
        for index, entry in enumerate(_entries(items)):
            if not isinstance(entry, dict) or not {"source", "type", "target"} <= entry.keys():
                raise ValidationError(
                    f'items[{index}]: use {{"source": key|id, "type": ..., "target": key|id}}'
                )
            rtype = entry["type"]
            if rtype not in LINK_RELATIONS:
                raise ValidationError(
                    f"items[{index}]: tipo de relação inválido: {rtype!r}. "
                    f"Válidos: {', '.join(LINK_RELATIONS)}"
                )
            source = _resolve(draft, entry["source"], index, "source")
            target = _resolve(draft, entry["target"], index, "target")
            if strict:
                if source is None:
                    raise _not_found(index, "source", entry["source"])
                if target is None:
                    raise _not_found(index, "target", entry["target"])
                if source.id == target.id:
                    raise ValidationError(f"items[{index}]: um item não pode se relacionar "
                                          "consigo mesmo")
            plan.append((index, rtype, source, target))
        return plan

    @staticmethod
    def _row(index: int, entry: dict[str, Any], action: str) -> dict[str, Any]:
        return {"index": index, "source": entry["source"], "type": entry["type"],
                "target": entry["target"], "action": action}

    def create(self, items: list[dict], viewpoint: Any = None) -> list[dict]:
        """Cria as ligações do lote (atômico). `unchanged` quando já existia.

        ValidationError (tipo inválido, mais de 20, auto-relação) e NotFoundError (ref fora da
        conexão) apontam a entrada `items[i]` e não gravam nada. Em modo PR, cada linha leva
        também `status` (`pending_review`/`issue_opened`) e `pr_url`/`issue_url`. `viewpoint` é
        ignorado (o alcance agora vem da hierarquia; a resolução é por id/key na conexão).
        """
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            rows = []
            for index, rtype, source, target in self._plan(d, items, strict=True):
                assert source is not None and target is not None
                created = d.add_link(source.id, rtype, target.id)
                rows.append(self._row(index, items[index], "created" if created else "unchanged"))
            extra: dict[str, Any] = {}
            if any(r["action"] == "created" for r in rows):
                extra = review_fields(brain.commit(d, f"knowledge-os: relaciona {len(rows)} "
                                                      "item(ns)"))
        logger.info("Relações: %d entrada(s)", len(rows))
        return [{**r, **extra} for r in rows]

    def delete(self, items: list[dict], viewpoint: Any = None) -> list[dict]:
        """Remove as ligações do lote (atômico). `missing` se a relação (ou uma ponta) não
        existe. `viewpoint` é ignorado."""
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            rows = []
            for index, rtype, source, target in self._plan(d, items, strict=False):
                gone = (source is not None and target is not None
                        and d.drop_link(source.id, rtype, target.id))
                rows.append(self._row(index, items[index], "deleted" if gone else "missing"))
            extra: dict[str, Any] = {}
            if any(r["action"] == "deleted" for r in rows):
                extra = review_fields(brain.commit(d, f"knowledge-os: remove {len(rows)} "
                                                      "relação(ões)"))
        return [{**r, **extra} for r in rows]

    def list(self, item_id: str) -> list[Relation]:
        """Ligações em que o item é origem ou alvo."""
        return [
            r for r in Brain(self._connection_id).snapshot.relations()
            if item_id in (r.source_item_id, r.target_item_id)
        ]

    def list_all(
        self, item_id: str | None = None, relation_type: str | None = None
    ) -> list[Relation]:
        """Todas as ligações da conexão, opcionalmente de um item e/ou de um tipo."""
        rows = Brain(self._connection_id).snapshot.relations()
        if item_id:
            rows = [r for r in rows if item_id in (r.source_item_id, r.target_item_id)]
        if relation_type:
            rows = [r for r in rows if r.relation_type == relation_type]
        return sorted(rows, key=lambda r: (r.source_item_id, r.relation_type, r.target_item_id))

    def list_for_items(self, item_ids: list[str]) -> list[Relation]:
        """Ligações cujos dois itens (origem e alvo) estão em `item_ids` — o grafo de um
        escopo qualquer (workspace/project/subject) é só filtrar os itens antes."""
        wanted = set(item_ids)
        if not wanted:
            return []
        return [
            r for r in Brain(self._connection_id).snapshot.relations()
            if r.source_item_id in wanted and r.target_item_id in wanted
        ]
