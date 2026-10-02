"""Helpers compartilhados pelos services."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Domain, Item, Workspace
from src.db.session import get_engine, get_session

EXPORT_VERSION = "1.0"


@contextmanager
def session_scope(session: Session | None) -> Iterator[Session]:
    """Usa a sessão informada ou abre (e fecha) uma via get_session(get_engine())."""
    if session is not None:
        yield session
        return
    own = get_session(get_engine())
    try:
        yield own
    finally:
        own.close()


def utc_now_iso() -> str:
    """Timestamp UTC em ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def workspace_to_dict(ws: Workspace) -> dict[str, Any]:
    """Serializa um Workspace."""
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "created_at": _iso(ws.created_at),
        "updated_at": _iso(ws.updated_at),
    }


def domain_to_dict(dm: Domain) -> dict[str, Any]:
    """Serializa um Domain."""
    return {
        "id": dm.id,
        "workspace_id": dm.workspace_id,
        "name": dm.name,
        "description": dm.description,
        "created_at": _iso(dm.created_at),
        "updated_at": _iso(dm.updated_at),
    }


def item_to_dict(item: Item) -> dict[str, Any]:
    """Serializa um Item (com nomes de tags e labels)."""
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "domain_id": item.domain_id,
        "type": item.type,
        "memory_class": item.memory_class,
        "title": item.title,
        "summary": item.summary,
        "content": item.content,
        "confidence": item.confidence,
        "importance": item.importance,
        "ttl_days": item.ttl_days,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
        "tags": sorted(t.name for t in item.tags),
        "labels": sorted(lb.name for lb in item.labels),
    }
