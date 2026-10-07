"""Testes do dialect de banco (hoje só SQLite: o índice de busca local de cada connection)."""

import pytest
from sqlalchemy import text

from knowledge_os.db.dialects import (
    DatabaseDialect,
    SQLiteDialect,
    get_dialect,
    redact,
)
from knowledge_os.db.models import Base
from knowledge_os.exceptions import ValidationError


def test_detect_from_url():
    assert DatabaseDialect.detect_from_url("sqlite:///./database/x.db") == "sqlite"
    assert DatabaseDialect.detect_from_url("sqlite://") == "sqlite"


def test_detect_from_url_invalida():
    with pytest.raises(ValidationError):
        DatabaseDialect.detect_from_url("postgresql://u:pw@h/db")
    with pytest.raises(ValidationError):
        DatabaseDialect.detect_from_url("isto nao e url")


def test_get_dialect_por_tipo():
    assert get_dialect("sqlite") is SQLiteDialect
    with pytest.raises(ValidationError):
        get_dialect("postgresql")
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


def test_redact_mascara_a_senha_e_suas_variantes_codificadas():
    url = "postgresql://u:p%40ss%20w@h/db"
    msg = "falha: p@ss w / p%40ss%20w / p%40ss+w"
    out = redact(msg, url)
    assert "p@ss w" not in out and "p%40ss%20w" not in out and "p%40ss+w" not in out
