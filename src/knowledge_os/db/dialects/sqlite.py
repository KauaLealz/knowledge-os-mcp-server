"""Dialect SQLite: WAL + FTS5 (tabela external content + triggers)."""

import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from knowledge_os.db.dialects.base import (
    FTS_COLUMNS,
    FTS_TABLE,
    FTS_TOKENIZE,
    FTS_WEIGHTS,
    DatabaseDialect,
)
from knowledge_os.exceptions import DatabaseError

logger = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 15000  # espera por trava de outro processo antes do "database is locked"


def _busy_timeout_ms() -> int:
    """15 s por padrão; KNOWLEDGE_OS_BUSY_TIMEOUT_MS existe para os testes."""
    try:
        return int(os.environ.get("KNOWLEDGE_OS_BUSY_TIMEOUT_MS", BUSY_TIMEOUT_MS))
    except ValueError:
        return BUSY_TIMEOUT_MS


def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Aplica PRAGMAs em cada nova conexão SQLite."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={_busy_timeout_ms()}")
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


_TRIGGERS = ("items_fts_ai", "items_fts_ad", "items_fts_au")


def _fts_ddl() -> str:
    cols = ", ".join(FTS_COLUMNS)
    return (
        f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5({cols}, content='items', "
        f"content_rowid='rowid', tokenize='{FTS_TOKENIZE}')"
    )


def _fts_sql(engine: Engine) -> str | None:
    """DDL atual da tabela FTS (None se ela não existe)."""
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"),
            {"n": FTS_TABLE},
        ).scalar()


def _fts_exists(engine: Engine) -> bool:
    return _fts_sql(engine) is not None


def _normalize(sql: str) -> str:
    return " ".join(sql.replace('"', "'").split()).lower()


class SQLiteDialect(DatabaseDialect):
    @staticmethod
    def create_engine(url: str) -> Engine:
        """Engine SQLite com WAL, synchronous=NORMAL, busy_timeout=15000 e foreign_keys=ON."""
        kwargs: dict[str, Any] = {"echo": False}
        connect_args: dict[str, Any] = {"check_same_thread": False}
        if url.endswith(":memory:") or url.endswith("sqlite://"):
            # Banco em memória: uma única conexão compartilhada, senão cada conexão
            # enxergaria um banco vazio diferente.
            kwargs["poolclass"] = StaticPool
        db_path = make_url(url).database
        if db_path and db_path != ":memory:":
            try:  # arquivo em subpasta ainda inexistente (ex.: <home>/database/x.db)
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass  # o erro de abertura do SQLite descreve o problema
        engine = create_engine(url, connect_args=connect_args, **kwargs)
        event.listen(engine, "connect", _set_sqlite_pragmas)
        return engine

    @staticmethod
    def supports_fts() -> bool:
        return True

    @staticmethod
    def create_fts_table(engine: Engine) -> None:
        """Cria (ou recria, se a definição mudou) a tabela FTS5 e os triggers.

        Uma definição antiga (outras colunas ou outro tokenizer) é descartada e o índice é
        reconstruído a partir de `items`: nenhum dado se perde, só o índice é refeito.
        """
        current = _fts_sql(engine)
        outdated = current is not None and _normalize(current) != _normalize(_fts_ddl())
        try:
            with engine.begin() as conn:
                if outdated:
                    logger.info("Recriando %s: definição mudou", FTS_TABLE)
                    for trigger in _TRIGGERS:
                        conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
                    conn.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
                if current is None or outdated:
                    conn.execute(text(_fts_ddl()))
                    # Indexa as linhas que já existiam antes da (re)criação do índice.
                    conn.execute(text(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild')"))
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Falha ao criar tabela FTS5: {exc}") from exc
        create_fts_trigger(engine)

    @staticmethod
    def search_parts(query: str) -> tuple[str, str, str, dict[str, Any]]:
        return (
            f"{FTS_TABLE} JOIN items i ON i.rowid = {FTS_TABLE}.rowid",
            f"{FTS_TABLE} MATCH :q",
            f"-bm25({FTS_TABLE}, {', '.join(str(w) for w in FTS_WEIGHTS)})",
            {"q": query},
        )
