"""Testes do MigrationService (SQLite -> outro banco)."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import knowledge_os.services.migration_service as migration_mod
from knowledge_os.db.migrations import bootstrap_labels
from knowledge_os.db.models import (
    Artifact,
    Item,
    ItemLabel,
    ItemTag,
    Label,
    Project,
    Relation,
    Tag,
    Workspace,
)
from knowledge_os.db.session import create_db_engine, init_db
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.migration_service import MigrationService
from tests.helpers_multidb import sqlite_url


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def source(tmp_path):
    """Banco SQLite de origem populado."""
    path = tmp_path / "source.db"
    engine = create_db_engine(sqlite_url(path))
    init_db(engine)
    with Session(engine) as s:
        ws = Workspace(id=_uid(), name="W", description="d")
        dm = Project(id=_uid(), workspace_id=ws.id, name="D")
        tag, lab = Tag(id=_uid(), name="k8s"), Label(id=_uid(), name="official")
        i1 = Item(id=_uid(), workspace_id=ws.id, project_id=dm.id, type="rule",
                  memory_class="longterm", title="Kubernetes", summary="s1", content="c1")
        i2 = Item(id=_uid(), workspace_id=ws.id, project_id=dm.id, type="rule",
                  memory_class="working", title="Outro", summary="s2", content="c2")
        s.add_all([ws, dm, tag, lab, i1, i2])
        s.flush()
        s.add_all([
            ItemTag(item_id=i1.id, tag_id=tag.id),
            ItemLabel(item_id=i1.id, label_id=lab.id),
            Relation(id=_uid(), source_item_id=i1.id, target_item_id=i2.id,
                     relation_type="related_to"),
            Artifact(id=_uid(), item_id=i1.id, filename="a.txt", file_path="nao-existe.txt",
                     file_size=3, mime_type="text/plain"),
        ])
        s.commit()
    engine.dispose()
    return path


def _count(url, table):
    engine = create_engine(url)
    with engine.connect() as c:
        n = c.execute(text(f"SELECT count(*) FROM {table}")).scalar()
    engine.dispose()
    return n


def test_migrate_preserves_data(source, tmp_path):
    target = sqlite_url(tmp_path / "target.db")
    result = MigrationService().migrate(sqlite_url(source), target)
    assert result["errors"] == []
    assert (result["workspaces"], result["projects"], result["items"]) == (1, 1, 2)
    engine = create_engine(target)
    with engine.connect() as c:
        row = c.execute(
            text("SELECT title, summary, content FROM items WHERE title='Kubernetes'")
        ).one()
        assert tuple(row) == ("Kubernetes", "s1", "c1")
        assert c.execute(text("SELECT count(*) FROM item_tags")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM item_labels")).scalar() == 1
        assert c.execute(text("SELECT connection_id FROM workspaces")).scalar() == "default"
        fts = c.execute(
            text("SELECT count(*) FROM items_fts WHERE items_fts MATCH 'kubernetes'")
        ).scalar()
        assert fts == 1
    engine.dispose()


def test_migrate_validates_counts(source, tmp_path):
    target = sqlite_url(tmp_path / "target.db")
    result = MigrationService().migrate(sqlite_url(source), target)
    for table in ("workspaces", "projects", "items", "tags", "relations", "artifacts"):
        assert _count(sqlite_url(source), table) == _count(target, table)
    assert result["relations"] == 1 and result["tags"] == 1


def test_migrate_artifacts_metadados_e_arquivo_ausente(source, tmp_path):
    target = sqlite_url(tmp_path / "target.db")
    result = MigrationService().migrate(sqlite_url(source), target)
    assert result["artifacts"] == 1
    assert result["warnings"] and "nao-existe.txt" in result["warnings"][0]


def test_migrate_labels_existentes_no_destino_sao_reaproveitadas(source, tmp_path):
    target = sqlite_url(tmp_path / "target.db")
    engine = create_db_engine(target)
    init_db(engine)
    with Session(engine) as s:
        bootstrap_labels(s)  # cria "official" com outro id
    engine.dispose()
    result = MigrationService().migrate(sqlite_url(source), target)
    assert result["errors"] == []
    assert _count(target, "labels") == 5
    assert _count(target, "item_labels") == 1


def test_migrate_conflito_e_atomico(source, tmp_path):
    target = sqlite_url(tmp_path / "target.db")
    MigrationService().migrate(sqlite_url(source), target)
    again = MigrationService().migrate(sqlite_url(source), target)  # duplicado
    assert again["errors"]
    assert _count(target, "items") == 2  # nada duplicado


def test_migrate_retag_connection_id(source, tmp_path):
    target = sqlite_url(tmp_path / "target.db")
    result = MigrationService().migrate(
        sqlite_url(source), target, connection_id="conn-x", connection_name="Destino")
    assert result["errors"] == []
    engine = create_engine(target)
    with engine.connect() as c:
        assert c.execute(text("SELECT connection_id FROM workspaces")).scalar() == "conn-x"
        name = c.execute(text("SELECT name FROM connections WHERE id='conn-x'")).scalar()
        assert name == "Destino"
    engine.dispose()


def test_migrate_origem_legada_sem_connection_id(tmp_path):
    legacy = tmp_path / "legacy.db"
    engine = create_engine(sqlite_url(legacy))
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) "
            "UNIQUE NOT NULL, description TEXT, created_at DATETIME, updated_at DATETIME)"))
        c.execute(text(
            "INSERT INTO workspaces (id, name, created_at) VALUES ('w1', 'Old', "
            "'2025-01-02 03:04:05.000000')"))
    engine.dispose()
    target = sqlite_url(tmp_path / "t.db")
    result = MigrationService().migrate(sqlite_url(legacy), target)
    assert result["errors"] == [] and result["workspaces"] == 1
    engine = create_engine(target)
    with engine.connect() as c:
        assert c.execute(text("SELECT connection_id FROM workspaces")).scalar() == "default"
    engine.dispose()


def test_migrate_origem_inexistente(tmp_path):
    with pytest.raises(NotFoundError):
        MigrationService().migrate_sqlite_to_postgresql(
            str(tmp_path / "nada.db"), "postgresql://u:p@h/db")


def test_migrate_sqlite_to_postgresql_valida_destino(source):
    with pytest.raises(ValidationError):
        MigrationService().migrate_sqlite_to_postgresql(str(source), "mysql://u:p@h/db")


def test_migrate_sqlite_to_postgresql_delega(source, monkeypatch):
    seen = {}

    def fake(self, source_url, target_url, **kw):
        seen.update(source_url=source_url, target_url=target_url)
        return {"errors": []}

    monkeypatch.setattr(migration_mod.MigrationService, "migrate", fake)
    MigrationService().migrate_sqlite_to_postgresql(str(source), "postgresql://u:p@h/db")
    assert seen["source_url"].startswith("sqlite:///")
    assert seen["target_url"].startswith("postgresql+psycopg://")


@pytest.mark.skipif(not os.getenv("KOS_TEST_POSTGRES_URL"), reason="sem PostgreSQL de teste")
def test_migrate_sqlite_to_postgresql_real(source):
    url = os.environ["KOS_TEST_POSTGRES_URL"]
    result = MigrationService().migrate_sqlite_to_postgresql(str(source), url)
    assert result["errors"] == [] and result["items"] == 2
