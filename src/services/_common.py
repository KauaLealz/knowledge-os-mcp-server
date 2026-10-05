"""Helpers compartilhados pelos services."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src.db.models import Connection, Domain, Item, Workspace
from src.db.session import get_engine, get_session

EXPORT_VERSION = "1.0"


@contextmanager
def session_scope(session: Session | None, connection_id: str | None = None) -> Iterator[Session]:
    """Usa a sessão informada ou abre (e fecha) uma no banco da connection.

    Sem connection_id usa o banco da conexão default do connections.json.
    """
    if session is not None:
        yield session
        return
    own = get_session(get_engine(connection_id) if connection_id else get_engine())
    try:
        yield own
    finally:
        own.close()


def tiebreak(s: Session, table: str) -> list[Any]:
    """Critério de desempate por ordem de inserção (rowid só existe no SQLite)."""
    bind = s.get_bind()
    return [text(f"{table}.rowid")] if bind.dialect.name == "sqlite" else []


def utc_now_iso() -> str:
    """Timestamp UTC em ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def connection_to_dict(conn: Connection) -> dict[str, Any]:
    """Serializa uma Connection. A URL sai sem senha; `password_set` diz só se existe."""
    return {
        "id": conn.id,
        "name": conn.name,
        "db_type": conn.db_type,
        "url": make_url(conn.db_url).render_as_string(hide_password=True),
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "username": conn.username,
        "password_set": bool(getattr(conn, "password_set", False)),
        "is_active": bool(conn.is_active),
        "last_tested": _iso(conn.last_tested),
        "test_result": conn.test_result,
        "created_at": _iso(conn.created_at),
        "updated_at": _iso(conn.updated_at),
    }


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
