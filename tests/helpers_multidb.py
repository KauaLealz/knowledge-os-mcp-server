"""Fixtures e helpers compartilhados pelos testes multi-conexão (T7)."""

from pathlib import Path

import pytest

import knowledge_os.db.session as session_mod
from knowledge_os.db.session import ConnectionManager, create_db_engine, init_db


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    """Catálogo (banco default) isolado em arquivo temporário + manager de teste."""
    engine = create_db_engine(sqlite_url(tmp_path / "catalog.db"))
    init_db(engine)
    manager = ConnectionManager(default_engine=engine)
    monkeypatch.setattr(session_mod, "_connection_manager", manager)
    yield manager
    manager.close_all()
