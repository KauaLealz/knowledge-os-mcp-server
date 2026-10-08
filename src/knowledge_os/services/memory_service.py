"""Memory service: promover e renovar itens."""

import dataclasses
import logging

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.brain import Brain, Item, utcnow

logger = logging.getLogger(__name__)

MEMORY_ORDER = ("ephemeral", "working", "longterm", "canonical")


class MemoryService:
    """Promoção e renovação de TTL dos itens da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def promote(self, item_id: str, target_memory: str) -> Item:
        """Promove o item para uma classe superior (nunca rebaixa nem vai para ephemeral).

        Ao sair de ephemeral, ttl_days é removido.
        """
        if target_memory not in MEMORY_ORDER:
            raise ValidationError(
                f"Classe de memória inválida: {target_memory}. Válidas: {', '.join(MEMORY_ORDER)}"
            )
        if target_memory == "ephemeral":
            raise ValidationError("Não é possível promover para ephemeral (sem downgrade)")
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            record = d.require(item_id)
            if record.memory_class not in MEMORY_ORDER:
                raise ValidationError(f"Classe atual desconhecida: {record.memory_class}")
            if MEMORY_ORDER.index(target_memory) <= MEMORY_ORDER.index(record.memory_class):
                raise ValidationError(
                    f"Promoção deve subir de classe: {record.memory_class} -> {target_memory}"
                )
            d.put(dataclasses.replace(record, memory_class=target_memory, ttl_days=None,
                                      updated_at=utcnow()))
            brain.commit(d, f"knowledge-os: promove {record.path} para {target_memory}")
        logger.info("Item %s promovido para %s", item_id, target_memory)
        return brain.view(brain.snapshot.require(item_id))

    def renew(self, item_id: str, ttl_days: int) -> Item:
        """Atualiza ttl_days de um item ephemeral; o prazo conta a partir de agora."""
        if ttl_days <= 0:
            raise ValidationError("ttl_days deve ser positivo")
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            record = d.require(item_id)
            if record.memory_class != "ephemeral":
                raise ValidationError(
                    f"Só itens ephemeral têm TTL (classe atual: {record.memory_class})"
                )
            # O vencimento é updated_at + ttl_days: renovar é gravar de novo agora.
            d.put(dataclasses.replace(record, ttl_days=ttl_days, updated_at=utcnow()))
            brain.commit(d, f"knowledge-os: renova {record.path}")
        logger.info("TTL do item %s renovado para %d dias", item_id, ttl_days)
        return brain.view(brain.snapshot.require(item_id))
