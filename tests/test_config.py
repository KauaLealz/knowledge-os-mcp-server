"""Testes do config de conexões (connections.json no home)."""

import pytest

from src.config import ConfigManager, ConnectionConfig, ConnectionsFile


def test_connection_config_valid(tmp_path):
    path = (tmp_path / "knowledge.db").as_posix()
    conn = ConnectionConfig(id="local", name="Local", db_type="sqlite", path=path)
    assert conn.get_url() == f"sqlite:///{path}"


def test_connection_config_id_invalid():
    with pytest.raises(ValueError):
        ConnectionConfig(id="INVALID_ID", name="Test", db_type="sqlite", path="./db.db")


def test_connection_config_port_invalid():
    with pytest.raises(ValueError):
        ConnectionConfig(id="pg", name="PG", db_type="postgresql", port=70000)


def test_connections_file_default_exists():
    with pytest.raises(ValueError):
        ConnectionsFile(version="1.0", default="nonexistent", connections=[])


def _pg(**kw):
    return ConnectionConfig(
        id="pg", name="PG", db_type="postgresql", host="h", port=5432,
        database="d", username="u", **kw,
    )


def test_get_url_postgres_with_and_without_password():
    assert _pg().get_url() == "postgresql://u@h:5432/d"
    assert _pg(password="p@ss").get_url() == "postgresql://u:p%40ss@h:5432/d"


def test_password_nunca_aparece_em_repr_str_ou_erro():
    conn = _pg(password="topsecret")
    cfg = ConnectionsFile(default="default", connections=[conn])
    for text in (repr(conn), str(conn), repr(cfg), str(cfg)):
        assert "topsecret" not in text
    bad = _pg(password="topsecret")
    bad.port = 1  # inalcançável
    msg = ConfigManager.validate_connection(bad)["message"]
    assert "topsecret" not in msg


def test_password_vai_para_o_json_e_password_env_saiu():
    conn = _pg(password="topsecret")
    assert conn.model_dump(mode="json")["password"] == "topsecret"
    assert not hasattr(conn, "password_env")
    assert "password_env" not in conn.model_dump()


def test_get_url_mysql():
    conn = ConnectionConfig(
        id="my", name="My", db_type="mysql", host="h", port=3306, database="d", username="u"
    )
    assert conn.get_url() == "mysql+pymysql://u@h:3306/d"


def test_create_default_config():
    config = ConfigManager.create_default_config()
    assert config.default == "default"
    assert config.connections == []


def test_load_or_create_creates_default(_isolated_home):
    config = ConfigManager.load_or_create()
    assert (_isolated_home / "connections.json").exists()
    assert config.default == "default"


def test_load_existing_config():
    config = ConfigManager.create_default_config()
    ConfigManager.save(config)
    loaded = ConfigManager.load_or_create()
    assert loaded.default == config.default
    assert len(loaded.connections) == len(config.connections)


def test_validate_connection_sqlite(tmp_path):
    conn = ConnectionConfig(
        id="local", name="Local", db_type="sqlite", path=(tmp_path / "v.db").as_posix()
    )
    assert ConfigManager.validate_connection(conn)["status"] == "ok"


def test_validate_connection_error():
    conn = ConnectionConfig(
        id="bad", name="Bad", db_type="postgresql", host="127.0.0.1", port=1,
        database="d", username="u",
    )
    assert ConfigManager.validate_connection(conn)["status"] == "error"


def _write_json(conns):
    import json

    ConfigManager.CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ConfigManager.CONNECTIONS_FILE.write_text(
        json.dumps({"version": "1.0", "default": "default", "connections": conns}),
        encoding="utf-8",
    )


def test_json_a_mao_sem_port_assume_o_padrao():
    _write_json([{"id": "pg", "name": "PG", "db_type": "postgresql", "host": "h",
                  "database": "d", "username": "u"},
                 {"id": "my", "name": "My", "db_type": "mysql", "host": "h", "database": "d"}])
    config = ConfigManager.load_or_create()
    assert config.get_connection("pg").get_url() == "postgresql://u@h:5432/d"
    assert config.get_connection("my").port == 3306


def test_json_com_host_ausente_aponta_conexao_e_campo_sem_vazar_senha():
    from src.exceptions import ConfigError
    from src.services.connection_service import ConnectionService

    _write_json([{"id": "pg", "name": "PG", "db_type": "postgresql",
                  "database": "d", "username": "u", "password": "SEGREDO-123"}])
    for call in (ConfigManager.load_or_create, ConnectionService().list):
        with pytest.raises(ConfigError) as err:
            call()
        msg = str(err.value)
        assert "pg" in msg and "host" in msg
        assert "SEGREDO" not in msg and "123" not in msg


@pytest.mark.parametrize("field", ["host", "database", "username"])
@pytest.mark.parametrize("bad", ["d?host=outro", "a#b", "a/b", "a\\b", "a@b", "a b"])
def test_campos_rejeitam_caracteres_de_injecao(field, bad):
    kw = {"host": "h", "database": "d", "username": "u", field: bad}
    with pytest.raises(ValueError):
        ConnectionConfig(id="pg", name="PG", db_type="postgresql", **kw)


def test_sqlite_exige_path():
    with pytest.raises(ValueError):
        ConnectionConfig(id="s", name="S", db_type="sqlite")
