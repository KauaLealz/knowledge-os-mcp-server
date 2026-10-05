"""Memory service: promover e renovar itens."""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from src.db.models import Item
from src.db.timeutil import utcnow
from src.exceptions import NotFoundError, ValidationError
from src.services._common import session_scope

logger = logging.getLogger(__name__)

MEMORY_ORDER = ("ephemeral", "working", "longterm", "canonical")


class MemoryService:
    """Promoção e renovação de TTL.

    Se `session` não for informada, cada operação abre uma sessão própria.
    """

    def __init__(
        self, session: Session | None = None, connection_id: str | None = None
    ) -> None:
        self._session = session
        self._connection_id = connection_id

    def _get_item(self, s: Session, item_id: str) -> Item:
        item = s.get(Item, item_id)
        if item is None:
            raise NotFoundError(f"Item não encontrado: {item_id}")
        return item

    def _finish(self, s: Session, item: Item) -> Item:
        s.commit()
        s.refresh(item)
        if self._session is None:
            s.expunge(item)
        return item

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
        with session_scope(self._session, self._connection_id) as s:
            item = self._get_item(s, item_id)
            if item.memory_class not in MEMORY_ORDER:
                raise ValidationError(f"Classe atual desconhecida: {item.memory_class}")
            if MEMORY_ORDER.index(target_memory) <= MEMORY_ORDER.index(item.memory_class):
                raise ValidationError(
                    f"Promoção deve subir de classe: {item.memory_class} -> {target_memory}"
                )
            if item.memory_class == "ephemeral":
                item.ttl_days = None
                item.expires_at = None
            item.memory_class = target_memory
            logger.info("Item %s promovido para %s", item_id, target_memory)
            return self._finish(s, item)

    def renew(self, item_id: str, ttl_days: int) -> Item:
        """Atualiza ttl_days de um item ephemeral."""
        if ttl_days <= 0:
            raise ValidationError("ttl_days deve ser positivo")
        with session_scope(self._session, self._connection_id) as s:
            item = self._get_item(s, item_id)
            if item.memory_class != "ephemeral":
                raise ValidationError(
                    f"Só itens ephemeral têm TTL (classe atual: {item.memory_class})"
                )
            item.ttl_days = ttl_days
            # Renovar conta a partir de agora: é o que o agente espera ao estender o prazo.
            item.expires_at = utcnow() + timedelta(days=ttl_days)
            logger.info("TTL do item %s renovado para %d dias", item_id, ttl_days)
            return self._finish(s, item)
