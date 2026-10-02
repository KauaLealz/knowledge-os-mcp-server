"""Memory service: promover e renovar itens."""

from sqlalchemy.orm import Session
from src.db.models import Item

# TODO: T4 - Implementar
# - promote(item_id, target_memory_class) -> Item
#   - ephemeral → working → longterm → canonical
#   - Se target é ephemeral, requer ttl_days
# - renew(item_id, ttl_days) -> Item
#   - Atualiza ttl_days para ephemeral
