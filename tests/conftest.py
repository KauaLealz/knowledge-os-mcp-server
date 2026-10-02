"""Pytest fixtures compartilhadas para testes."""

import os
import tempfile
import uuid
from typing import Generator

# Home de dados da suíte: definido antes de qualquer import de `src`, para que as
# constantes lidas no import (DB_PATH, ARTIFACTS_DIR...) nunca apontem para o ~/.knowledge-os real.
os.environ["KNOWLEDGE_OS_HOME"] = tempfile.mkdtemp(prefix="kos-test-home-")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.config as config  # noqa: E402
from src.config import ConfigManager  # noqa: E402
from src.db.models import Base, Domain, Item, Label, Tag, Workspace  # noqa: E402
from src.db.session import create_fts_trigger  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Cada teste tem o seu home: connections.json e paths relativos vivem em tmp_path."""
    home = tmp_path / "home"
    monkeypatch.setattr(config, "KNOWLEDGE_HOME", home)
    monkeypatch.setattr(ConfigManager, "CONNECTIONS_FILE", home / "connections.json")
    return home


@pytest.fixture
def test_engine():
    """Engine SQLite em memória para testes."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    # Criar tabelas
    Base.metadata.create_all(bind=engine)

    # Criar tabela virtual FTS5
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS items_fts
                USING fts5(title, summary, content, content='items', content_rowid='rowid')
                """
            )
        )
        conn.execute(text("INSERT INTO items_fts(items_fts) VALUES('rebuild')"))

    # Criar triggers
    create_fts_trigger(engine)

    yield engine

    engine.dispose()


@pytest.fixture
def test_session(test_engine) -> Generator[Session, None, None]:
    """Sessão SQLAlchemy para testes."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = SessionLocal()

    yield session

    session.close()


@pytest.fixture
def sample_workspace(test_session: Session) -> Workspace:
    """Cria um workspace para testes."""
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="TestWorkspace",
        description="Workspace para testes"
    )
    test_session.add(ws)
    test_session.commit()
    return ws


@pytest.fixture
def sample_domain(test_session: Session, sample_workspace: Workspace) -> Domain:
    """Cria um domain para testes."""
    dm = Domain(
        id=str(uuid.uuid4()),
        workspace_id=sample_workspace.id,
        name="TestDomain",
        description="Domain para testes"
    )
    test_session.add(dm)
    test_session.commit()
    return dm


@pytest.fixture
def sample_item(test_session: Session, sample_workspace: Workspace, sample_domain: Domain) -> Item:
    """Cria um item para testes."""
    item = Item(
        id=str(uuid.uuid4()),
        workspace_id=sample_workspace.id,
        domain_id=sample_domain.id,
        type="knowledge",
        memory_class="longterm",
        title="Test Item",
        summary="Test summary about ConditionalOnProperty",
        content="Test content with keywords about Spring beans and conditional logic",
        confidence=90,
        importance=5
    )
    test_session.add(item)
    test_session.commit()
    return item


@pytest.fixture
def sample_label(test_session: Session) -> Label:
    """Cria uma label para testes."""
    label = Label(
        id=str(uuid.uuid4()),
        name="test_label"
    )
    test_session.add(label)
    test_session.commit()
    return label


@pytest.fixture
def sample_tag(test_session: Session) -> Tag:
    """Cria uma tag para testes."""
    tag = Tag(
        id=str(uuid.uuid4()),
        name="test_tag"
    )
    test_session.add(tag)
    test_session.commit()
    return tag
