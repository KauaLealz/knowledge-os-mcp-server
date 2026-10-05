"""Testes do CRUD de Connection (service + modelo). O cadastro é o connections.json."""

import os

import pytest
from sqlalchemy import create_engine, inspect

from knowledge_os.config import ConfigManager
from knowledge_os.db.models import DEFAULT_CONNECTION_ID, Connection, Workspace
from knowledge_os.db.session import ensure_connection_row, get_engine
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import connection_to_dict, session_scope
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.workspace_service import WorkspaceService
from tests.helpers_multidb import catalog, sqlite_url  # noqa: F401


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    """O .knowledge/connections.json (caminho relativo) fica isolado em tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def svc(catalog):  # noqa: F811
    return ConnectionService()


def test_connection_create_sqlite(svc, tmp_path):
    conn = svc.create("Local", "sqlite", sqlite_url(tmp_path / "a.db"))
    assert conn.id and conn.name == "Local" and conn.db_type == "sqlite"
    assert conn.is_active is True
    assert conn.test_result == "connected" and conn.last_tested is not None
    assert (tmp_path / "a.db").exists()


def test_connection_create_grava_no_json_e_sincroniza_schema(svc, tmp_path):
    conn = svc.create("Local", "sqlite", sqlite_url(tmp_path / "sync.db"))
    saved = ConfigManager.load_or_create().get_connection(conn.id)
    assert saved.name == "Local" and saved.db_type == "sqlite" and saved.enabled is True
    assert saved.path == (tmp_path / "sync.db").as_posix()
    engine = create_engine(sqlite_url(tmp_path / "sync.db"))
    try:
        assert {"workspaces", "items", "items_fts", "connections"} <= set(
            inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_connection_create_sem_teste(svc, tmp_path):
    conn = svc.create("Local", "sqlite", sqlite_url(tmp_path / "b.db"), test=False)
    assert conn.last_tested is None and conn.test_result is None
    assert not (tmp_path / "b.db").exists()  # sem teste, não toca no banco
    assert svc.get("Local").id == conn.id  # mas já está no JSON


def test_connection_create_recusa_senha_na_url(svc):
    with pytest.raises(ValidationError, match="password") as exc:
        svc.create("Pw", "postgresql", "postgresql://u:secret@prod/knowledge", test=False)
    assert "secret" not in str(exc.value)
    assert ConfigManager.load_or_create().connections == []


def test_connection_create_mysql(svc):
    conn = svc.create(
        "My", "mysql", "mysql://root@db.local:3307/personal", test=False, password="s3cret")
    assert conn.db_type == "mysql"
    assert (conn.host, conn.port, conn.database, conn.username) == (
        "db.local", 3307, "personal", "root")
    assert conn.db_url.startswith("mysql+pymysql://")
    assert ConfigManager.load_or_create().get_connection(conn.id).password == "s3cret"


def test_connection_create_postgresql(svc):
    conn = svc.create("Pg", "postgresql", "postgresql://u@prod:5432/knowledge", test=False)
    assert conn.db_type == "postgresql"
    assert (conn.host, conn.port, conn.database, conn.username) == ("prod", 5432, "knowledge", "u")
    assert conn.db_url.startswith("postgresql+psycopg://")


def test_connection_create_postgresql_sem_porta_usa_a_padrao(svc):
    conn = svc.create("Pg", "postgresql", "postgresql://localhost/test", test=False)
    assert conn.port == 5432 and conn.database == "test"


@pytest.mark.parametrize("db_type,url", [
    ("mysql", "mysql://root@127.0.0.1:1/x"),
    ("postgresql", "postgresql://u@127.0.0.1:1/x"),
])
def test_connection_create_inalcancavel_falha_sem_vazar_senha(svc, db_type, url):
    with pytest.raises(ValidationError) as exc:
        svc.create("Down", db_type, url, test=True, password="topsecret")
    assert "topsecret" not in str(exc.value)
    assert [c.id for c in svc.list()] == [DEFAULT_CONNECTION_ID]
    assert ConfigManager.load_or_create().connections == []


def test_connection_create_validacoes(svc, tmp_path):
    url = sqlite_url(tmp_path / "v.db")
    with pytest.raises(ValidationError):
        svc.create("", "sqlite", url)
    with pytest.raises(ValidationError):
        svc.create("X", "oracle", url)
    with pytest.raises(ValidationError):
        svc.create("X", "postgresql", url)  # tipo diverge da URL
    with pytest.raises(ValidationError):
        svc.create("default", "sqlite", url)  # nome reservado
    svc.create("Ok", "sqlite", url)
    with pytest.raises(ValidationError):
        svc.create("Ok", "sqlite", sqlite_url(tmp_path / "w.db"))  # nome duplicado


def test_connection_test_sqlite(svc, tmp_path):
    conn = svc.create("Local", "sqlite", sqlite_url(tmp_path / "t.db"), test=False)
    result = svc.test(conn.id)
    assert result["status"] == "ok" and result["latency_ms"] >= 0


@pytest.mark.parametrize("db_type,url", [
    ("mysql", "mysql://root@127.0.0.1:1/x"),
    ("postgresql", "postgresql://u@127.0.0.1:1/x"),
])
def test_connection_test_falha_nao_vaza_senha(svc, db_type, url):
    conn = svc.create("Down", db_type, url, test=False, password="topsecret")
    result = svc.test(conn.id)
    assert result["status"] == "error" and "topsecret" not in result["message"]


def test_connection_get_e_list(svc, tmp_path):
    a = svc.create("A", "sqlite", sqlite_url(tmp_path / "1.db"))
    b = svc.create("B", "sqlite", sqlite_url(tmp_path / "2.db"))
    assert svc.get(a.id).name == "A"
    assert svc.get("A").id == a.id  # por nome
    assert [c.name for c in svc.list()][-2:] == ["A", "B"]
    assert svc.list()[0].id == DEFAULT_CONNECTION_ID
    assert svc.get(DEFAULT_CONNECTION_ID).id == DEFAULT_CONNECTION_ID
    with pytest.raises(NotFoundError):
        svc.get("nao-existe")
    assert b.id != a.id


def test_connection_update(svc, tmp_path):
    a = svc.create("A", "sqlite", sqlite_url(tmp_path / "1.db"))
    svc.create("B", "sqlite", sqlite_url(tmp_path / "2.db"))
    upd = svc.update(a.id, name="A2", is_active=False)
    assert upd.name == "A2" and upd.is_active is False
    saved = ConfigManager.load_or_create().get_connection(a.id)
    assert saved.name == "A2" and saved.enabled is False
    with pytest.raises(ValidationError):
        svc.update(a.id, name="B")
    with pytest.raises(ValidationError):
        svc.update(a.id, db_url="x")
    with pytest.raises(ValidationError):
        svc.update(DEFAULT_CONNECTION_ID, is_active=False)
    with pytest.raises(NotFoundError):
        svc.update("nao-existe", name="Z")


def test_connection_delete_cascade(svc, tmp_path):
    conn = svc.create("A", "sqlite", sqlite_url(tmp_path / "1.db"))
    ensure_connection_row(get_engine(), conn.id, "A")  # espelho da FK no catálogo
    # workspaces do catálogo vinculados à connection somem em cascata
    with session_scope(None) as s:
        s.add(Workspace(id="w-cascade", connection_id=conn.id, name="W"))
        s.commit()
    assert svc.delete(conn.id) is True
    with session_scope(None) as s:
        assert s.get(Workspace, "w-cascade") is None
        assert s.get(Connection, conn.id) is None
    assert svc.delete(conn.id) is False
    assert conn.id not in [c.id for c in ConfigManager.load_or_create().connections]


def test_connection_delete_default_proibido(svc):
    with pytest.raises(ValidationError):
        svc.delete(DEFAULT_CONNECTION_ID)


def test_workspace_with_connection(svc, tmp_path):
    conn = svc.create("A", "sqlite", sqlite_url(tmp_path / "1.db"))
    ws = WorkspaceService(connection_id=conn.id).create("W", "desc")
    assert ws.connection_id == conn.id
    assert WorkspaceService().list() == []  # o default não enxerga


def test_serializacao_oculta_senha_e_informa_password_set(svc, tmp_path):
    conn = svc.create(
        "Pg", "postgresql", "postgresql://u@prod/knowledge", test=False, password="topsecret")
    data = connection_to_dict(svc.get(conn.id))
    assert "topsecret" not in str(data) and "topsecret" not in str(connection_to_dict(conn))
    assert data["password_set"] is True
    assert data["host"] == "prod" and data["db_type"] == "postgresql"
    local = svc.create("L", "sqlite", sqlite_url(tmp_path / "l.db"), test=False)
    assert connection_to_dict(svc.get(local.id))["password_set"] is False
    assert connection_to_dict(svc.get(DEFAULT_CONNECTION_ID))["password_set"] is False
    assert all("topsecret" not in str(connection_to_dict(c)) for c in svc.list())


def test_senha_fica_no_json_com_chmod_600_quando_o_so_permite(svc):
    svc.create("Pg", "postgresql", "postgresql://u@prod/knowledge", test=False, password="pw1")
    path = ConfigManager.CONNECTIONS_FILE
    assert '"password": "pw1"' in path.read_text(encoding="utf-8")
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(not os.getenv("KOS_TEST_POSTGRES_URL"), reason="sem PostgreSQL de teste")
def test_connection_test_postgresql_real(svc):
    conn = svc.create("PgLive", "postgresql", os.environ["KOS_TEST_POSTGRES_URL"])
    assert svc.test(conn.id)["status"] == "ok"


@pytest.mark.skipif(not os.getenv("KOS_TEST_MYSQL_URL"), reason="sem MySQL de teste")
def test_connection_test_mysql_real(svc):
    conn = svc.create("MyLive", "mysql", os.environ["KOS_TEST_MYSQL_URL"])
    assert svc.test(conn.id)["status"] == "ok"


def test_test_do_catalogo_usa_o_engine_vivo_e_nao_a_url_do_espelho(svc, monkeypatch):
    from sqlalchemy import text

    from knowledge_os.services import connection_service

    monkeypatch.setattr(connection_service, "_last_tests", {})  # estado global do módulo

    with get_engine(DEFAULT_CONNECTION_ID).begin() as c:  # espelho com URL gravada errada
        c.execute(text("UPDATE connections SET db_url = 'postgresql://u@127.0.0.1:1/d' "
                       "WHERE id = 'default'"))
    result = svc.test(DEFAULT_CONNECTION_ID)
    assert result["status"] == "ok", result
