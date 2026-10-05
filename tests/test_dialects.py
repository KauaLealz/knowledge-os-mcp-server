"""Testes dos dialects de banco (SQLite, MySQL, PostgreSQL)."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from src.db.dialects import (
    DatabaseDialect,
    MySQLDialect,
    PostgreSQLDialect,
    SQLiteDialect,
    get_dialect,
    normalize_url,
    redact,
)
from src.db.models import Base
from src.exceptions import ValidationError


@pytest.mark.parametrize("url,expected", [
    ("sqlite:///./database/x.db", "sqlite"),
    ("sqlite://", "sqlite"),
    ("mysql://root:pw@localhost/knowledge", "mysql"),
    ("mysql+pymysql://root:pw@localhost/knowledge", "mysql"),
    ("mariadb://root:pw@localhost/knowledge", "mysql"),
    ("postgresql://u:pw@h:5432/knowledge", "postgresql"),
    ("postgresql+psycopg://u:pw@h/knowledge", "postgresql"),
    ("postgres://u:pw@h/knowledge", "postgresql"),
])
def test_detect_from_url(url, expected):
    assert DatabaseDialect.detect_from_url(url) == expected


def test_detect_from_url_invalida():
    with pytest.raises(ValidationError):
        DatabaseDialect.detect_from_url("oracle://u:p@h/db")
    with pytest.raises(ValidationError):
        DatabaseDialect.detect_from_url("isto nao e url")


def test_normalize_url_adiciona_drivers():
    assert normalize_url("mysql://u:p@h/db").startswith("mysql+pymysql://")
    assert normalize_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_url("postgres://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_url("sqlite:///x.db") == "sqlite:///x.db"
    assert normalize_url("mysql+pymysql://u:p@h/db") == "mysql+pymysql://u:p@h/db"


def test_get_dialect_por_tipo():
    assert get_dialect("sqlite") is SQLiteDialect
    assert get_dialect("mysql") is MySQLDialect
    assert get_dialect("postgresql") is PostgreSQLDialect
    with pytest.raises(ValidationError):
        get_dialect("oracle")


def test_sqlite_engine_aplica_pragmas(tmp_path):
    engine = SQLiteDialect.create_engine(f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
    engine.dispose()


def test_sqlite_fts(tmp_path):
    assert SQLiteDialect.supports_fts() is True
    engine = SQLiteDialect.create_engine(f"sqlite:///{(tmp_path / 'f.db').as_posix()}")
    Base.metadata.create_all(engine)
    SQLiteDialect.create_fts_table(engine)
    SQLiteDialect.create_fts_table(engine)  # idempotente
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM items_fts")).scalar() == 0
        names = {
            r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        }
    assert {"items_fts_ai", "items_fts_ad", "items_fts_au"} <= names
    engine.dispose()


def test_sqlite_search_parts_usa_match():
    source, where, score, params = SQLiteDialect.search_parts("kubernetes")
    assert "items_fts" in source and "MATCH" in where and "bm25" in score
    assert params == {"q": "kubernetes"}


def test_postgresql_engine_dialect():
    engine = PostgreSQLDialect.create_engine("postgresql://u:pw@localhost:5432/knowledge")
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


def test_postgresql_fts():
    assert PostgreSQLDialect.supports_fts() is True
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    PostgreSQLDialect.create_fts_table(engine)
    sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list).lower()
    assert "pg_trgm" in sql and "items_fts_idx" in sql and "gin" in sql and "to_tsvector" in sql


def test_postgresql_search_parts_usa_tsvector():
    source, where, score, params = PostgreSQLDialect.search_parts("kubernetes")
    assert "to_tsvector" in where and "plainto_tsquery" in where
    assert "ts_rank" in score and params == {"q": "kubernetes"}


def test_mysql_engine_dialect():
    engine = MySQLDialect.create_engine("mysql://root:pw@localhost/knowledge")
    assert engine.dialect.name == "mysql"
    assert engine.dialect.driver == "pymysql"
    engine.dispose()


def test_mysql_sem_fts_nativo():
    assert MySQLDialect.supports_fts() is False
    engine = MagicMock()
    MySQLDialect.create_fts_table(engine)  # fallback LIKE: nada a criar
    engine.begin.assert_not_called()
    engine.connect.assert_not_called()


def test_mysql_search_parts_usa_like_escapado():
    source, where, score, params = MySQLDialect.search_parts("50%_off")
    assert "LIKE" in where and score == "0.0"
    assert params["q"] == "%50\\%\\_off%"


def test_redact_mascara_a_senha_e_suas_variantes_codificadas():
    url = "postgresql://u:p%40ss%20w@h/db"
    msg = "falha: p@ss w / p%40ss%20w / p%40ss+w"
    out = redact(msg, url)
    assert "p@ss w" not in out and "p%40ss%20w" not in out and "p%40ss+w" not in out
