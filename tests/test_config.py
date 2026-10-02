"""Testes do config de conexões (.knowledge/connections.json)."""

from pathlib import Path

import pytest

from src.config import ConfigManager, ConnectionConfig, ConnectionsFile


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_connection_config_valid():
    conn = ConnectionConfig(
        id="sqlite_local", name="Local", db_type="sqlite", path="./knowledge.db"
    )
    assert conn.get_url() == "sqlite:///./knowledge.db"


def test_connection_config_id_invalid():
    with pytest.raises(ValueError):
        ConnectionConfig(id="INVALID_ID", name="Test", db_type="sqlite", path="./db.db")


def test_connection_config_port_invalid():
    with pytest.raises(ValueError):
        ConnectionConfig(id="pg", name="PG", db_type="postgresql", port=70000)


def test_connections_file_default_exists():
    with pytest.raises(ValueError):
        ConnectionsFile(version="1.0", default="nonexistent", connections=[])


def test_get_url_postgres_with_and_without_password(monkeypatch):
    conn = ConnectionConfig(
        id="pg", name="PG", db_type="postgresql", host="h", port=5432,
        database="d", username="u", password_env="KOS_TEST_PW",
    )
    monkeypatch.delenv("KOS_TEST_PW", raising=False)
    assert conn.get_url() == "postgresql://u@h:5432/d"
    monkeypatch.setenv("KOS_TEST_PW", "p@ss")
    assert conn.get_url() == "postgresql://u:p%40ss@h:5432/d"


def test_get_url_mysql():
    conn = ConnectionConfig(
        id="my", name="My", db_type="mysql", host="h", port=3306, database="d", username="u"
    )
    assert conn.get_url() == "mysql+pymysql://u@h:3306/d"


def test_create_default_config():
    config = ConfigManager.create_default_config()
    assert config.default == "sqlite_local"
    assert len(config.connections) == 1
    assert config.connections[0].db_type == "sqlite"


def test_load_or_create_creates_default(workdir):
    config = ConfigManager.load_or_create()
    assert Path(".knowledge/connections.json").exists()
    assert config.default == "sqlite_local"


def test_load_existing_config(workdir):
    config = ConfigManager.create_default_config()
    ConfigManager.save(config)
    loaded = ConfigManager.load_or_create()
    assert loaded.default == config.default
    assert len(loaded.connections) == len(config.connections)


def test_validate_connection_sqlite(workdir):
    conn = ConfigManager.create_default_config().connections[0]
    assert ConfigManager.validate_connection(conn)["status"] == "ok"


def test_validate_connection_error(workdir):
    conn = ConnectionConfig(
        id="bad", name="Bad", db_type="postgresql", host="127.0.0.1", port=1,
        database="d", username="u",
    )
    assert ConfigManager.validate_connection(conn)["status"] == "error"
