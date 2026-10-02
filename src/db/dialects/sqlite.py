"""Dialect SQLite: WAL + FTS5 (tabela external content + triggers)."""

import logging
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from src.db.dialects.base import FTS_COLUMNS, FTS_TABLE, DatabaseDialect
from src.exceptions import DatabaseError

logger = logging.getLogger(__name__)


def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Aplica PRAGMAs em cada nova conexão SQLite."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_fts_trigger(engine: Engine) -> None:
    """Cria triggers que mantêm items_fts sincronizado com a tabela items."""
    cols = ", ".join(FTS_COLUMNS)
    new_vals = ", ".join(f"new.{c}" for c in FTS_COLUMNS)
    old_vals = ", ".join(f"old.{c}" for c in FTS_COLUMNS)
    delete_row = (
        f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, {cols}) "
        f"VALUES('delete', old.rowid, {old_vals});"
    )
    insert_row = f"INSERT INTO {FTS_TABLE}(rowid, {cols}) VALUES (new.rowid, {new_vals});"
    statements = [
        f"CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN {insert_row} END",
        f"CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN {delete_row} END",
        f"CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE OF {cols} ON items "
        f"BEGIN {delete_row} {insert_row} END",
    ]
    try:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
    except SQLAlchemyError as exc:
        raise DatabaseError(f"Falha ao criar triggers FTS5: {exc}") from exc


def _fts_exists(engine: Engine) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
            {"n": FTS_TABLE},
        ).first()
    return row is not None


class SQLiteDialect(DatabaseDialect):
    @staticmethod
    def create_engine(url: str) -> Engine:
        """Engine SQLite com WAL, synchronous=NORMAL, busy_timeout=5000 e foreign_keys=ON."""
        kwargs: dict[str, Any] = {"echo": False}
        connect_args: dict[str, Any] = {"check_same_thread": False, "timeout": 10}
        if url.endswith(":memory:") or url.endswith("sqlite://"):
            # Banco em memória: uma única conexão compartilhada, senão cada conexão
            # enxergaria um banco vazio diferente.
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, connect_args=connect_args, **kwargs)
        event.listen(engine, "connect", _set_sqlite_pragmas)
        return engine

    @staticmethod
    def supports_fts() -> bool:
        return True

    @staticmethod
    def create_fts_table(engine: Engine) -> None:
        """Cria a tabela virtual FTS5 (external content sobre items) e os triggers."""
        existed = _fts_exists(engine)
        cols = ", ".join(FTS_COLUMNS)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} "
                        f"USING fts5({cols}, content='items', content_rowid='rowid')"
                    )
                )
                if not existed:
                    # Indexa linhas que já existiam antes da criação do índice.
                    conn.execute(text(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild')"))
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Falha ao criar tabela FTS5: {exc}") from exc
        create_fts_trigger(engine)

    @staticmethod
    def search_parts(query: str) -> tuple[str, str, str, dict[str, Any]]:
        return (
            f"{FTS_TABLE} JOIN items i ON i.rowid = {FTS_TABLE}.rowid",
            f"{FTS_TABLE} MATCH :q",
            f"-bm25({FTS_TABLE})",
            {"q": query},
        )
