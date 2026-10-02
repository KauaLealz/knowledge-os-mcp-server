"""Dialect MySQL: sem FTS ranqueado; a busca cai para LIKE."""

from typing import Any

from sqlalchemy import Engine, create_engine

from src.db.dialects.base import CONNECT_TIMEOUT_S, DatabaseDialect, normalize_url


class MySQLDialect(DatabaseDialect):
    @staticmethod
    def create_engine(url: str) -> Engine:
        # mysql+pymysql://root:password@localhost/knowledge
        return create_engine(
            normalize_url(url),
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
        )

    @staticmethod
    def supports_fts() -> bool:
        return False  # fallback para LIKE

    @staticmethod
    def create_fts_table(engine: Engine) -> None:
        """Nada a criar: a busca usa LIKE (sem scores ranqueados)."""

    @staticmethod
    def search_parts(query: str) -> tuple[str, str, str, dict[str, Any]]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return (
            "items i",
            "(i.title LIKE :q OR i.summary LIKE :q OR i.content LIKE :q)",
            "0.0",
            {"q": f"%{escaped}%"},
        )
