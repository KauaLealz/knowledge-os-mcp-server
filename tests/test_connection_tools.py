"""Testes das tools schema_sync e migrate_workspaces (config em arquivo)."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.config import ConfigManager, ConnectionConfig
from src.mcp.connection_tools import migrate_workspaces, schema_sync


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Config com a conexão "sqlite_local" (knowledge.db em tmp_path)."""
    monkeypatch.chdir(tmp_path)
    config = ConfigManager.create_default_config()
    config.connections.append(
        ConnectionConfig(
            id="sqlite_local", name="Local SQLite", db_type="sqlite",
            path=(tmp_path / "knowledge.db").as_posix(),
        )
    )
    ConfigManager.save(config)
    return tmp_path


def _two_sqlite():
    config = ConfigManager.load_or_create()
    backup = (Path(config.get_connection("sqlite_local").path).parent / "backup.db").as_posix()
    config.connections.append(
        ConnectionConfig(id="sqlite_backup", name="Backup", db_type="sqlite", path=backup)
    )
    ConfigManager.save(config)


def _count(path, table):
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as c:
            return c.execute(text(f"SELECT count(*) FROM {table}")).scalar()
    finally:
        engine.dispose()


def _seed_workspace(path, name):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO workspaces (id, name, connection_id) "
                f"VALUES ('{name}-id', '{name}', 'default')"
            )
        )
    engine.dispose()


def _tables(path):
    from sqlalchemy import inspect

    engine = create_engine(f"sqlite:///{path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_schema_sync_creates(workdir):
    result = schema_sync("sqlite_local", dry_run=False)
    assert result["status"] == "created"
    assert result["connection_id"] == "sqlite_local"
    assert _count(workdir / "knowledge.db", "workspaces") == 0
    assert schema_sync("sqlite_local")["status"] == "up_to_date"


def test_schema_sync_dry_run(workdir):
    result = schema_sync("sqlite_local", dry_run=True)
    assert result["status"] == "created"
    assert result["dry_run"] is True
    assert "workspaces" in result["tables_created"]
    assert "workspaces" not in _tables(workdir / "knowledge.db")


def test_schema_sync_not_found(workdir):
    result = schema_sync("nonexistent_conn")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower()


def test_migrate_syncs_destination(workdir):
    _two_sqlite()
    schema_sync("sqlite_local")
    _seed_workspace(workdir / "knowledge.db", "A")
    backup = workdir / "backup.db"
    assert not backup.exists() or "workspaces" not in _tables(backup)
    result = migrate_workspaces("sqlite_local", "sqlite_backup", mode="replace")
    assert result["status"] == "success", result
    assert _count(workdir / "backup.db", "workspaces") == 1


def test_migrate_workspaces_connection_not_found(workdir):
    result = migrate_workspaces("nonexistent", "sqlite_local")
    assert result["status"] == "error"


def test_migrate_workspaces_invalid_mode(workdir):
    result = migrate_workspaces("sqlite_local", "sqlite_local", mode="invalid")
    assert result["status"] == "error"
    assert "replace" in result["message"].lower()


def test_migrate_workspaces_replace(workdir):
    _two_sqlite()
    schema_sync("sqlite_local")
    schema_sync("sqlite_backup")
    _seed_workspace(workdir / "knowledge.db", "A")
    _seed_workspace(workdir / "backup.db", "OLD")
    result = migrate_workspaces("sqlite_local", "sqlite_backup", mode="replace")
    assert result["status"] == "success", result
    assert result["workspaces_migrated"] == 1
    assert _count(workdir / "backup.db", "workspaces") == 1


def test_migrate_workspaces_merge(workdir):
    _two_sqlite()
    schema_sync("sqlite_local")
    schema_sync("sqlite_backup")
    _seed_workspace(workdir / "knowledge.db", "A")
    _seed_workspace(workdir / "backup.db", "OLD")
    result = migrate_workspaces("sqlite_local", "sqlite_backup", mode="merge")
    assert result["status"] == "success", result
    assert _count(workdir / "backup.db", "workspaces") == 2


def test_migrate_workspaces_same_connection(workdir):
    result = migrate_workspaces("sqlite_local", "sqlite_local")
    assert result["status"] == "error"


def test_tools_connection_nao_recebem_senha_e_devolvem_password_set(workdir):
    import asyncio

    import src.main as main

    main.register_all_tools()
    tools = asyncio.run(main.mcp.get_tools())
    for name in ("connection_create", "connection_update"):
        assert not [p for p in tools[name].parameters["properties"] if "pass" in p], name

    config = ConfigManager.load_or_create()
    config.connections.append(ConnectionConfig(
        id="pg", name="Pg", db_type="postgresql", host="h", port=5432, database="d",
        username="u", password="topsecret", enabled=False))
    ConfigManager.save(config)

    from fastmcp import FastMCP

    from src.mcp.connection_tools import register

    m = FastMCP(name="t")
    register(m)
    local = asyncio.run(m.get_tools())
    got = local["connection_get"].fn(connection_id="pg")
    listed = local["connection_list"].fn()
    assert got["password_set"] is True
    assert "topsecret" not in str(got) and "topsecret" not in str(listed)


def _pg_conn(cid, password):
    return ConnectionConfig(
        id=cid, name=cid.upper(), db_type="postgresql", host="h", port=5432,
        database="d", username="u", password=password,
    )


def test_erros_das_tools_nao_vazam_a_senha(workdir, monkeypatch):
    from src.mcp import connection_tools

    config = ConfigManager.load_or_create()
    config.connections += [_pg_conn("pg1", "SENHA-UM"), _pg_conn("pg2", "SENHA-DOIS")]
    ConfigManager.save(config)

    def boom(conn, dry_run):
        raise RuntimeError(f"falha em {conn.get_url()}")

    monkeypatch.setattr(connection_tools, "_sync_connection", boom)
    monkeypatch.setattr(
        ConfigManager, "validate_connection", lambda c: {"status": "ok", "message": ""}
    )
    msg = schema_sync("pg1")["message"]
    assert "SENHA-UM" not in msg and "falha em" in msg
    msg = migrate_workspaces("pg1", "pg2")["message"]
    assert "SENHA-DOIS" not in msg and "SENHA-UM" not in msg and "falha em" in msg
