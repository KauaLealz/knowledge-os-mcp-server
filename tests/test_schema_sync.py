"""Testes do schema_sync: cria o que falta, reporta o destrutivo, respeita dry_run."""

from sqlalchemy import inspect, text

from knowledge_os.db.models import Base
from knowledge_os.db.schema_sync import SCHEMA_META_TABLE, schema_sync
from knowledge_os.db.session import create_db_engine


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


def _fresh(tmp_path):
    from knowledge_os.db.session import create_db_engine

    return create_db_engine(f"sqlite:///{tmp_path / 'novo.db'}")


def test_primeiro_start_tolera_create_all_que_outro_processo_ganhou(tmp_path, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from knowledge_os.db.models import Base

    real = Base.metadata.create_all

    def create_then_lose(*a, **kw):
        real(*a, **kw)  # o outro processo criou primeiro
        raise OperationalError("CREATE TABLE", {}, Exception("table items already exists"))

    monkeypatch.setattr(Base.metadata, "create_all", create_then_lose)
    engine = _fresh(tmp_path)
    assert schema_sync(engine)["status"] == "created"
    engine.dispose()


def test_primeiro_start_tolera_fts_que_outro_processo_criou(tmp_path, monkeypatch):
    from knowledge_os.db.dialects.sqlite import SQLiteDialect
    from knowledge_os.exceptions import DatabaseError

    real = SQLiteDialect.create_fts_table

    calls = []

    def create_then_lose(engine):
        real(engine)
        if not calls:
            calls.append(1)
            raise DatabaseError("Falha ao criar tabela FTS5: table items_fts already exists")

    monkeypatch.setattr(SQLiteDialect, "create_fts_table", staticmethod(create_then_lose))
    engine = _fresh(tmp_path)
    schema_sync(engine)
    engine.dispose()


def test_conflito_ao_gravar_a_versao_le_de_novo_e_segue(tmp_path, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from knowledge_os.db import schema_sync as mod

    real = mod._write_version
    calls = []

    def lose_once(engine, version):
        calls.append(1)
        real(engine, version)  # o outro processo gravou a mesma versão
        raise IntegrityError("INSERT", {}, Exception("duplicate key schema_meta_pkey"))

    monkeypatch.setattr(mod, "_write_version", lose_once)
    engine = _fresh(tmp_path)
    schema_sync(engine)
    assert mod._read_version(engine) == mod.model_version()
    engine.dispose()


def test_dois_processos_subindo_num_home_vazio(tmp_path):
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    go = tmp_path / "go"
    code = (
        "import sys, time, pathlib\n"
        "from knowledge_os.db.session import create_db_engine\n"
        "from knowledge_os.db.schema_sync import schema_sync\n"
        "e = create_db_engine(sys.argv[1])\n"
        "while not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.001)\n"
        "print(schema_sync(e)['status'])\n"
    )
    env = {**os.environ, "PYTHONPATH": str(root / "src"),
           "KNOWLEDGE_OS_HOME": str(tmp_path / "home")}
    url = f"sqlite:///{tmp_path / 'vazio.db'}"
    procs = [subprocess.Popen([sys.executable, "-c", code, url, str(go)], env=env, cwd=root,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    time.sleep(3)
    go.write_text("go")
    outs = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
