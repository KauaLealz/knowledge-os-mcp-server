"""Helpers compartilhados pelos services."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import knowledge_os.config as config
from knowledge_os.db.models import Connection, Item, Project, Subject, Workspace
from knowledge_os.db.session import get_engine, get_session
from knowledge_os.exceptions import ValidationError

EXPORT_VERSION = "1.0"


def purge_item_links(s: Session, item_ids: list[str]) -> None:
    """Apaga o que referencia os itens (tags, labels, relações) antes de removê-los.

    Com foreign_keys=ON no SQLite, remover workspace ou project com itens que têm tags
    ou relações falhava por chave estrangeira: o cascade do ORM só cobre a tabela items.
    """
    from sqlalchemy import delete

    from knowledge_os.db.models import ItemLabel, ItemTag, Relation, SecretValue

    if not item_ids:
        return
    s.execute(delete(ItemTag).where(ItemTag.item_id.in_(item_ids)))
    s.execute(delete(ItemLabel).where(ItemLabel.item_id.in_(item_ids)))
    s.execute(
        delete(Relation).where(
            Relation.source_item_id.in_(item_ids) | Relation.target_item_id.in_(item_ids)
        )
    )
    s.execute(delete(SecretValue).where(SecretValue.item_id.in_(item_ids)))


def refuse_home_source(path: Path) -> None:
    """ValidationError se o caminho (resolvido, seguindo symlinks) está dentro do home de dados.

    Protege connections.json (senhas) e os índices SQLite de virar pasta de uma connection
    nova. O home é lido na chamada.
    """
    resolved = path.resolve()
    if resolved.is_relative_to(config.KNOWLEDGE_HOME.resolve()):
        raise ValidationError("Caminho dentro do home de dados não é permitido")


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
    """Serializa uma Connection: repositório git (clone local) + índice de busca."""
    return {
        "id": conn.id,
        "name": conn.name,
        "url": make_url(conn.db_url).render_as_string(hide_password=True),
        "remote_url": getattr(conn, "remote_url", None),
        "review_mode": getattr(conn, "review_mode", "direct"),
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


def project_to_dict(dm: Project) -> dict[str, Any]:
    """Serializa um Project."""
    return {
        "id": dm.id,
        "workspace_id": dm.workspace_id,
        "name": dm.name,
        "description": dm.description,
        "created_at": _iso(dm.created_at),
        "updated_at": _iso(dm.updated_at),
    }


def subject_to_dict(sj: Subject) -> dict[str, Any]:
    """Serializa um Subject."""
    return {
        "id": sj.id,
        "project_id": sj.project_id,
        "name": sj.name,
        "description": sj.description,
        "created_at": _iso(sj.created_at),
        "updated_at": _iso(sj.updated_at),
    }


def item_to_dict(item: Item) -> dict[str, Any]:
    """Serializa um Item (com nomes de tags e labels)."""
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "project_id": item.project_id,
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
