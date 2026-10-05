"""Dialects de banco suportados (SQLite, MySQL, PostgreSQL)."""

from knowledge_os.db.dialects.base import DatabaseDialect, detect_type, normalize_url, redact
from knowledge_os.db.dialects.mysql import MySQLDialect
from knowledge_os.db.dialects.postgresql import PostgreSQLDialect
from knowledge_os.db.dialects.sqlite import SQLiteDialect
from knowledge_os.exceptions import ValidationError

DB_TYPES = ("sqlite", "mysql", "postgresql")

_DIALECTS: dict[str, type[DatabaseDialect]] = {
    "sqlite": SQLiteDialect,
    "mysql": MySQLDialect,
    "postgresql": PostgreSQLDialect,
}


def get_dialect(db_type: str) -> type[DatabaseDialect]:
    """Retorna a classe de dialect do tipo informado (ValidationError se desconhecido)."""
    try:
        return _DIALECTS[db_type]
    except KeyError:
        raise ValidationError(
            f"db_type inválido: {db_type!r} (use {', '.join(DB_TYPES)})"
        ) from None


__all__ = [
    "DB_TYPES",
    "DatabaseDialect",
    "MySQLDialect",
    "PostgreSQLDialect",
    "SQLiteDialect",
    "detect_type",
    "get_dialect",
    "normalize_url",
    "redact",
]
