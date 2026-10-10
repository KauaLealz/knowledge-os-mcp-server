"""Relation service: relações semânticas entre itens, guardadas no frontmatter da origem.

`create`/`delete` trabalham em lote (até 20 entradas `{source, type, target}`), atômicos: toda
entrada é resolvida e validada antes de qualquer mudança, e o lote vira uma publicação só.
`source`/`target` são key ou id, resolvidos pela cadeia de alcance do repositório
(`scope.resolve_key`). Um `supersedes` também arquiva o alvo, na mesma publicação.
"""

from __future__ import annotations

import logging
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import RELATION_TYPES
from knowledge_os.services import scope
from knowledge_os.services.brain import Brain, Draft, Relation, utcnow
from knowledge_os.services.git_repo_service import PublishResult
from knowledge_os.storage.files import ItemRecord

logger = logging.getLogger(__name__)

MAX_BATCH = 20

__all__ = ["RELATION_TYPES", "RelationService", "review_fields"]


def review_fields(result: PublishResult | None) -> dict[str, Any]:
    """Em modo PR a mudança só vale após o merge: o que o chamador precisa para avisar."""
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
            f"key|id}}. Tipos: {', '.join(RELATION_TYPES)}"
        )
    if len(items) > MAX_BATCH:
        raise ValidationError(f"no máximo {MAX_BATCH} relações por chamada (recebi {len(items)})")
    return items


def _resolve(draft: Draft, ref: Any, viewpoint: scope.Viewpoint, index: int, role: str,
             ) -> ItemRecord | None:
    if not isinstance(ref, str) or not ref.strip():
        raise ValidationError(f"items[{index}]: '{role}' deve ser a key ou o id de um item")
    return scope.resolve_key(draft, ref.strip(), viewpoint)


def _not_found(index: int, role: str, ref: str) -> NotFoundError:
    return NotFoundError(
        f"items[{index}]: {role} '{ref}' não existe no alcance deste repositório. Confira a key "
        "(item_search), use o id do item, ou ligue o repo ao project dele / dê a ele scope "
        "workspace ou global"
    )


class RelationService:
    """Operações sobre relações entre itens da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    @staticmethod
    def _plan(draft: Draft, items: Any, viewpoint: scope.Viewpoint, *, strict: bool,
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
            if rtype not in RELATION_TYPES:
                raise ValidationError(
                    f"items[{index}]: tipo de relação inválido: {rtype!r}. "
                    f"Válidos: {', '.join(RELATION_TYPES)}"
                )
            source = _resolve(draft, entry["source"], viewpoint, index, "source")
            target = _resolve(draft, entry["target"], viewpoint, index, "target")
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

    def create(self, items: list[dict], viewpoint: scope.Viewpoint = None) -> list[dict]:
        """Cria as relações do lote (atômico). `unchanged` quando já existia.

        ValidationError (tipo inválido, mais de 20, auto-relação) e NotFoundError (key fora do
        alcance) apontam a entrada `items[i]` e não gravam nada. Em modo PR, cada linha leva
        também `status` (`pending_review`/`issue_opened`) e `pr_url`/`issue_url`.
        """
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            rows = []
            for index, rtype, source, target in self._plan(d, items, viewpoint, strict=True):
                assert source is not None and target is not None
                created = d.add_link(source.id, rtype, target.id)
                if created and rtype == "supersedes" and target.status != "archived":
                    # O substituído sai da busca e do pacote, sem perder o histórico.
                    d.update(target.id, status="archived", updated_at=utcnow())
                rows.append(self._row(index, items[index], "created" if created else "unchanged"))
            extra: dict[str, Any] = {}
            if any(r["action"] == "created" for r in rows):
                extra = review_fields(brain.commit(d, f"knowledge-os: relaciona {len(rows)} "
                                                      "item(ns)"))
        logger.info("Relações: %d entrada(s)", len(rows))
        return [{**r, **extra} for r in rows]

    def delete(self, items: list[dict], viewpoint: scope.Viewpoint = None) -> list[dict]:
        """Remove as relações do lote (atômico). `missing` se a relação (ou uma ponta) não
        existe. Remover um `supersedes` não reativa o alvo: o status se ajusta com item_save."""
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            rows = []
            for index, rtype, source, target in self._plan(d, items, viewpoint, strict=False):
                gone = (source is not None and target is not None
                        and d.drop_link(source.id, rtype, target.id))
                rows.append(self._row(index, items[index], "deleted" if gone else "missing"))
            extra: dict[str, Any] = {}
            if any(r["action"] == "deleted" for r in rows):
                extra = review_fields(brain.commit(d, f"knowledge-os: remove {len(rows)} "
                                                      "relação(ões)"))
        return [{**r, **extra} for r in rows]

    def list(self, item_id: str) -> list[Relation]:
        """Relações em que o item é origem ou alvo."""
        return [
            r for r in Brain(self._connection_id).snapshot.relations()
            if item_id in (r.source_item_id, r.target_item_id)
        ]

    def list_all(
        self, item_id: str | None = None, relation_type: str | None = None
    ) -> list[Relation]:
        """Todas as relações da conexão, opcionalmente de um item e/ou de um tipo."""
        rows = Brain(self._connection_id).snapshot.relations()
        if item_id:
            rows = [r for r in rows if item_id in (r.source_item_id, r.target_item_id)]
        if relation_type:
            rows = [r for r in rows if r.relation_type == relation_type]
        return sorted(rows, key=lambda r: (r.source_item_id, r.relation_type, r.target_item_id))

    def list_for_items(self, item_ids: list[str]) -> list[Relation]:
        """Relações cujos dois itens (origem e alvo) estão em `item_ids` — o grafo de um
        escopo qualquer (workspace/project/subject) é só filtrar os itens antes."""
        wanted = set(item_ids)
        if not wanted:
            return []
        return [
            r for r in Brain(self._connection_id).snapshot.relations()
            if r.source_item_id in wanted and r.target_item_id in wanted
        ]
