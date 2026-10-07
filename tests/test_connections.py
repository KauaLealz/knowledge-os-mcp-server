"""Testes do CRUD de Connection (service + modelo). O cadastro é o connections.json."""

import itertools
import os
import subprocess
from pathlib import Path

import pytest

from knowledge_os.config import ConfigManager
from knowledge_os.db.models import DEFAULT_CONNECTION_ID, Connection, Workspace
from knowledge_os.db.session import ensure_connection_row, get_engine
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import connection_to_dict, session_scope
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.workspace_service import WorkspaceService
from tests.helpers_multidb import catalog  # noqa: F401


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    """O .knowledge/connections.json (caminho relativo) fica isolado em tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def svc(catalog, tmp_path):  # noqa: F811
    """`create()` sem `path` ganha uma pasta nova em tmp_path — os testes deste arquivo
    exercitam name/remote_url/review_mode, não o path em si (ver test_connection_service_path.py).
    """
    real = ConnectionService()
    counter = itertools.count()

    class _Svc:
        def __getattr__(self, attr):
            return getattr(real, attr)

        def create(self, name, path=None, **kwargs):
            if path is None:
                path = tmp_path / f"repo-{next(counter)}"
                Path(path).mkdir(parents=True, exist_ok=True)
            return real.create(name, str(path), **kwargs)

    return _Svc()


def _bare_repo(tmp_path, name="remote.git"):
    """Repositório git bare local: um remote de verdade, clonável sem rede."""
    path = tmp_path / name
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)
    return str(path)


def test_connection_create_local_sem_remote(svc):
    conn = svc.create("Local")
    assert conn.id and conn.name == "Local"
    assert conn.is_active is True
    assert conn.test_result == "Repositório local (sem remote)" and conn.last_tested is not None


def test_connection_create_grava_no_json_e_prepara_o_repo(svc):
    conn = svc.create("Local")
    saved = ConfigManager.load_or_create().get_connection(conn.id)
    assert saved.name == "Local" and saved.enabled is True and saved.remote_url is None
    assert (saved.clone_path() / ".git").is_dir()
    import sqlite3

    from knowledge_os.config import INDEXES_DIR

    index_path = INDEXES_DIR / f"{saved.id}.db"
    with sqlite3.connect(index_path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"workspaces", "items", "connections"} <= tables


def test_connection_create_sem_teste(svc):
    conn = svc.create("Local", test=False)
    assert conn.last_tested is None and conn.test_result is None
    assert svc.get("Local").id == conn.id  # mas já está no JSON


def test_connection_create_com_review_mode_pr(svc):
    conn = svc.create("Local", review_mode="pr")
    assert conn.review_mode == "pr"


def test_connection_create_validacoes(svc):
    with pytest.raises(ValidationError):
        svc.create("")
    with pytest.raises(ValidationError):
        svc.create("default")  # nome reservado
    svc.create("Ok")
    with pytest.raises(ValidationError):
        svc.create("Ok")  # nome duplicado


def test_connection_test_sem_remote(svc):
    conn = svc.create("Local", test=False)
    result = svc.test(conn.id)
    assert result["status"] == "ok" and result["latency_ms"] >= 0


def test_connection_create_com_remote_inalcancavel_falha(svc):
    with pytest.raises(ValidationError):
        svc.create("Down", remote_url="https://127.0.0.1:1/nope.git", test=True)
    assert [c.id for c in svc.list()] == [DEFAULT_CONNECTION_ID]
    assert ConfigManager.load_or_create().connections == []


def test_connection_test_com_remote_inalcancavel_nao_levanta(svc, tmp_path):
    remote = _bare_repo(tmp_path)
    conn = svc.create("Down", remote_url=remote, test=False)
    import shutil

    shutil.rmtree(remote)  # o remote deixa de existir depois de cadastrado
    result = svc.test(conn.id)
    assert result["status"] == "error"


def test_connection_get_e_list(svc):
    a = svc.create("A")
    b = svc.create("B")
    assert svc.get(a.id).name == "A"
    assert svc.get("A").id == a.id  # por nome
    assert [c.name for c in svc.list()][-2:] == ["A", "B"]
    assert svc.list()[0].id == DEFAULT_CONNECTION_ID
    assert svc.get(DEFAULT_CONNECTION_ID).id == DEFAULT_CONNECTION_ID
    with pytest.raises(NotFoundError):
        svc.get("nao-existe")
    assert b.id != a.id


def test_connection_update(svc):
    a = svc.create("A")
    svc.create("B")
    upd = svc.update(a.id, name="A2", is_active=False)
    assert upd.name == "A2" and upd.is_active is False
    saved = ConfigManager.load_or_create().get_connection(a.id)
    assert saved.name == "A2" and saved.enabled is False
    with pytest.raises(ValidationError):
        svc.update(a.id, name="B")
    with pytest.raises(ValidationError):
        svc.update(a.id, review_mode="sync")
    with pytest.raises(ValidationError):
        svc.update(DEFAULT_CONNECTION_ID, is_active=False)
    with pytest.raises(NotFoundError):
        svc.update("nao-existe", name="Z")


def test_connection_update_remote_url(svc):
    a = svc.create("A")
    upd = svc.update(a.id, remote_url="https://github.com/acme/repo.git")
    assert upd.remote_url == "https://github.com/acme/repo.git"
    upd = svc.update(a.id, remote_url=None)
    assert upd.remote_url is None


def test_connection_delete_cascade(svc):
    conn = svc.create("A")
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


def test_connection_delete_nao_apaga_clone_nem_indice(svc):
    conn = svc.create("A")
    from knowledge_os.config import ConfigManager as CM

    config = CM.load_or_create()
    clone_path = config.get_connection(conn.id).clone_path()
    assert clone_path.exists()
    svc.delete(conn.id)
    assert clone_path.exists()  # dado do usuário: não é apagado automaticamente


def test_connection_delete_default_proibido(svc):
    with pytest.raises(ValidationError):
        svc.delete(DEFAULT_CONNECTION_ID)


def test_workspace_with_connection(svc):
    conn = svc.create("A")
    ws = WorkspaceService(connection_id=conn.id).create("W")
    assert ws.connection_id == conn.id
    assert WorkspaceService().list() == []  # o default não enxerga


def test_serializacao_mostra_remote_url_e_review_mode(svc, tmp_path):
    remote = _bare_repo(tmp_path)
    conn = svc.create("A", remote_url=remote, test=False)
    data = connection_to_dict(svc.get(conn.id))
    assert data["remote_url"] == remote
    assert data["review_mode"] == "direct"
    local = svc.create("L", test=False)
    assert connection_to_dict(svc.get(local.id))["remote_url"] is None
    assert connection_to_dict(svc.get(DEFAULT_CONNECTION_ID))["remote_url"] is None


def test_conexoes_ficam_no_json_com_o_remote_url(svc, tmp_path):
    remote = _bare_repo(tmp_path)
    svc.create("A", remote_url=remote, test=False)
    path = ConfigManager.CONNECTIONS_FILE
    assert f'"remote_url": "{remote}"' in path.read_text(encoding="utf-8")
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
