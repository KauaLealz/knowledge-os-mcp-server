"""Dialect PostgreSQL: busca textual com tsvector + índice GIN."""

import logging
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from knowledge_os.db.dialects.base import (
    CONNECT_TIMEOUT_S,
    DatabaseDialect,
    normalize_url,
    require_driver,
)
from knowledge_os.exceptions import DatabaseError

logger = logging.getLogger(__name__)

FTS_CONFIG = "portuguese"


def _vector(alias: str = "") -> str:
    return (
        f"to_tsvector('{FTS_CONFIG}', coalesce({alias}title, '') || ' ' || "
        f"coalesce({alias}summary, '') || ' ' || coalesce({alias}keywords, '') || ' ' || "
        f"coalesce({alias}content, ''))"
    )


class PostgreSQLDialect(DatabaseDialect):
    @staticmethod
    def create_engine(url: str) -> Engine:
        # postgresql+psycopg://user:password@localhost/knowledge
        require_driver("psycopg", "postgres")
        return create_engine(
            normalize_url(url),
            echo=False,
            pool_pre_ping=True,
            connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
        )

    @staticmethod
    def supports_fts() -> bool:
        return True  # tsvector

    @staticmethod
    def create_fts_table(engine: Engine) -> None:
        """Habilita pg_trgm (se permitido) e cria o índice GIN sobre o tsvector."""
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        except SQLAlchemyError as exc:  # sem privilégio: a busca por tsvector não depende dela
            logger.warning("pg_trgm indisponível: %s", exc)
        try:
            with engine.begin() as conn:
                # v2: o vetor passou a incluir keywords; o índice antigo não serviria à busca.
                conn.execute(text("DROP INDEX IF EXISTS items_fts_idx"))
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS items_fts_v2_idx ON items "
                        f"USING gin({_vector()})"
                    )
                )
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Falha ao criar índice FTS (tsvector): {exc}") from exc

    @staticmethod
    def search_parts(query: str) -> tuple[str, str, str, dict[str, Any]]:
        vector = _vector("i.")
        tsquery = f"plainto_tsquery('{FTS_CONFIG}', :q)"
        return (
            "items i",
            f"{vector} @@ {tsquery}",
            f"ts_rank({vector}, {tsquery})",
            {"q": query},
        )
