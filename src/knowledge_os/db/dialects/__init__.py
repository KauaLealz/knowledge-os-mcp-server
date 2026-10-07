"""Dialect de banco suportado: só SQLite (um índice de busca local por connection)."""

from knowledge_os.db.dialects.base import DatabaseDialect, detect_type, redact
from knowledge_os.db.dialects.sqlite import SQLiteDialect
from knowledge_os.exceptions import ValidationError

DB_TYPES = ("sqlite",)

_DIALECTS: dict[str, type[DatabaseDialect]] = {
    "sqlite": SQLiteDialect,
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
    "SQLiteDialect",
    "detect_type",
    "get_dialect",
    "redact",
]
