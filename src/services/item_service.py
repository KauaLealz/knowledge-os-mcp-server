"""Item service: CRUD, search, FTS5."""

from sqlalchemy.orm import Session
from src.db.models import Item

# TODO: T3 - Implementar
# - create(workspace_id, domain_id, type, memory_class, title, summary, content, tags, labels, confidence, importance, ttl_days) -> Item
# - update(item_id, **fields) -> Item
# - delete(item_id) -> bool
# - get(item_id) -> Item (com content)
# - search(workspace_id, domain_id, query, types, memory_classes, limit) -> [{id, title, summary, score}]
#   - Usa FTS5 em title+summary+content
#   - Retorna summary, não content
#   - Score baseado em BM25
