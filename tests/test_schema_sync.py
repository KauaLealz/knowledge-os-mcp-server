"""Testes do schema_sync: cria o que falta, reporta o destrutivo, respeita dry_run."""

from sqlalchemy import inspect, text

from src.db.models import Base
from src.db.schema_sync import SCHEMA_META_TABLE, schema_sync
from src.db.session import create_db_engine


def create_test_engine():
    return create_db_engine("sqlite:///:memory:")


def _tables(engine):
    return set(inspect(engine).get_table_names())


def test_sync_creates_tables_if_missing():
    """Banco vazio: cria tabelas, índices e FTS."""
    engine = create_test_engine()
    result = schema_sync(engine, dry_run=False)
    assert result["status"] == "created"
    assert set(result["tables_created"]) == set(Base.metadata.tables)
    tables = _tables(engine)
    assert set(Base.metadata.tables) <= tables
    assert "items_fts" in tables
    assert SCHEMA_META_TABLE in tables
    index_names = {i["name"] for i in inspect(engine).get_indexes("items")}
    assert "idx_item_type" in index_names


def test_sync_adds_column_if_missing():
    """Coluna faltando: adiciona e reporta."""
    engine = create_test_engine()
    schema_sync(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE domains DROP COLUMN description"))
    result = schema_sync(engine, dry_run=False)
    assert result["status"] == "updated"
    assert result["columns_added"] == ["domains.description"]
    cols = {c["name"] for c in inspect(engine).get_columns("domains")}
    assert "description" in cols


def test_sync_adds_not_null_column_with_default():
    """Coluna NOT NULL com default do modelo (caso workspaces.connection_id)."""
    engine = create_test_engine()
    schema_sync(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE workspaces"))
        conn.execute(text(
            "CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
            "description TEXT, created_at DATETIME, updated_at DATETIME)"
        ))
        conn.execute(text("INSERT INTO workspaces (id, name) VALUES ('w1', 'old')"))
    result = schema_sync(engine)
    assert result["status"] == "updated"
    assert "workspaces.connection_id" in result["columns_added"]
    assert "workspaces.idx_workspace_connection" in result["indexes_created"]
    with engine.connect() as conn:
        value = conn.execute(text("SELECT connection_id FROM workspaces")).scalar()
    assert value == "default"


def test_sync_adds_index_if_missing():
    engine = create_test_engine()
    schema_sync(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX idx_item_type"))
    result = schema_sync(engine)
    assert result["status"] == "updated"
    assert result["indexes_created"] == ["items.idx_item_type"]


def test_sync_up_to_date():
    engine = create_test_engine()
    schema_sync(engine)
    result = schema_sync(engine)
    assert result["status"] == "up_to_date"
    assert result["pending_manual"] == []


def test_sync_detects_drift():
    """Tipo de coluna diferente: reporta sem alterar."""
    engine = create_test_engine()
    schema_sync(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE relations"))
        conn.execute(text(
            "CREATE TABLE relations (id VARCHAR(36) PRIMARY KEY, "
            "source_item_id VARCHAR(36) NOT NULL, target_item_id VARCHAR(36) NOT NULL, "
            "relation_type INTEGER NOT NULL, created_at DATETIME)"
        ))
    result = schema_sync(engine, dry_run=False)
    assert result["status"] == "drift"
    assert any("relations.relation_type" in p for p in result["pending_manual"])
    types = {c["name"]: str(c["type"]) for c in inspect(engine).get_columns("relations")}
    assert types["relation_type"] == "INTEGER"


def test_sync_dry_run():
    """dry_run=True não altera o banco, mas lista o que seria aplicado."""
    engine = create_test_engine()
    result = schema_sync(engine, dry_run=True)
    assert result["status"] == "created"
    assert result["dry_run"] is True
    assert set(result["tables_created"]) == set(Base.metadata.tables)
    assert len(inspect(engine).get_table_names()) == 0


def test_sync_dry_run_does_not_add_column():
    engine = create_test_engine()
    schema_sync(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE domains DROP COLUMN description"))
    result = schema_sync(engine, dry_run=True)
    assert result["status"] == "updated"
    assert result["columns_added"] == ["domains.description"]
    assert "description" not in {c["name"] for c in inspect(engine).get_columns("domains")}


def test_sync_records_version():
    engine = create_test_engine()
    result = schema_sync(engine)
    with engine.connect() as conn:
        stored = conn.execute(
            text(f"SELECT value FROM {SCHEMA_META_TABLE} WHERE key = 'schema_version'")
        ).scalar()
    assert stored == result["version"]
