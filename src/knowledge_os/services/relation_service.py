"""Relation service: relações semânticas entre itens, guardadas no frontmatter da origem.

Criar ou remover uma relação regrava o arquivo do item de origem (e, num `supersedes`, o do
alvo, que passa a `superseded`) e publica pelo repositório git da conexão.
"""

from __future__ import annotations

import logging

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.brain import Brain, Relation, relation_id, utcnow

logger = logging.getLogger(__name__)

RELATION_TYPES = (
    "related_to",
    "depends_on",
    "implements",
    "references",
    "supersedes",
    "derived_from",
)


class RelationService:
    """Operações sobre relações entre itens da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def create(self, source_item_id: str, target_item_id: str, relation_type: str) -> Relation:
        """Cria a relação (idempotente: a mesma relação não duplica).

        ValidationError para tipo inválido/auto-relação; NotFoundError se item não existe.
        """
        if relation_type not in RELATION_TYPES:
            raise ValidationError(
                f"relation_type inválido: {relation_type}. Válidos: {', '.join(RELATION_TYPES)}"
            )
        if source_item_id == target_item_id:
            raise ValidationError("Um item não pode se relacionar consigo mesmo")
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            source = d.require(source_item_id)
            target = d.require(target_item_id)
            d.add_link(source.id, relation_type, target.id)
            if relation_type == "supersedes" and target.status != "superseded":
                # O substituído sai da busca e do pacote de contexto, sem perder o histórico.
                d.update(target.id, status="superseded", updated_at=utcnow())
            brain.commit(d, f"knowledge-os: relaciona {source.path}")
        logger.info("Relação criada: %s %s %s", source_item_id, relation_type, target_item_id)
        return Relation(
            relation_id(source_item_id, relation_type, target_item_id),
            source_item_id, target_item_id, relation_type,
        )

    create_published = create

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

    def delete(self, relation_id_: str) -> bool:
        """Remove a relação (regrava o item de origem). NotFoundError se não existe.

        Remover um `supersedes` não reativa o alvo: o status dele se ajusta com item_save.
        """
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            rel = d.relation(relation_id_)
            d.drop_link(rel.source_item_id, rel.relation_type, rel.target_item_id)
            source = d.require(rel.source_item_id)
            brain.commit(d, f"knowledge-os: remove relação de {source.path}")
        logger.info("Relação removida: %s", relation_id_)
        return True

    delete_published = delete
