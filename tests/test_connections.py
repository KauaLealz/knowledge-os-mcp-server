"""Testes do CRUD de Connection (service + modelo). O cadastro é o connections.json."""

import itertools
import json
import os
import subprocess
from pathlib import Path

import pytest

from knowledge_os.config import NO_CONNECTION_MESSAGE, ConfigManager
from knowledge_os.exceptions import NoConnectionError, NotFoundError, ValidationError
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.workspace_service import WorkspaceService


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    """Caminhos relativos ficam isolados em tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def svc(tmp_path):
    """`create()` sem `path` ganha uma pasta nova em tmp_path."""
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


def test_sem_conexao_a_lista_e_vazia_e_nada_e_criado(svc, _isolated_home):
    assert svc.list() == []
    assert not (_isolated_home / "connections.json").exists()
    with pytest.raises(NoConnectionError) as exc:
        WorkspaceService().list()
    assert str(exc.value) == NO_CONNECTION_MESSAGE


def test_connection_create_local_sem_remote(svc):
    conn = svc.create("Local")
    assert conn.id and conn.name == "Local"
    assert conn.is_active is True
    assert conn.test_result == "Repositório local (sem remote)" and conn.last_tested is not None


def test_primeira_conexao_vira_a_padrao(svc):
    a = svc.create("A", test=False)
    b = svc.create("B", test=False)
    assert a.is_default is True and b.is_default is False
    assert ConfigManager.load().default == a.id


def test_connection_create_grava_no_json_e_prepara_o_repo(svc):
    conn = svc.create("Local")
    saved = ConfigManager.load().get_connection(conn.id)
    assert saved.name == "Local" and saved.enabled is True and saved.remote_url is None
    assert (saved.clone_path() / ".git").is_dir()


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
    assert svc.list() == []
    assert ConfigManager.load().connections == []


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
    assert [c.name for c in svc.list()] == ["A", "B"]
    with pytest.raises(NotFoundError):
        svc.get("nao-existe")
    assert b.id != a.id


def test_connection_update(svc):
    a = svc.create("A")
    b = svc.create("B")
    upd = svc.update(b.id, name="B2", is_active=False)
    assert upd.name == "B2" and upd.is_active is False
    saved = ConfigManager.load().get_connection(b.id)
    assert saved.name == "B2" and saved.enabled is False
    with pytest.raises(ValidationError):
        svc.update(b.id, name="A")
    with pytest.raises(ValidationError):
        svc.update(b.id, review_mode="sync")
    with pytest.raises(ValidationError):
        svc.update(a.id, is_active=False)  # a padrão não pode ser desativada
    with pytest.raises(NotFoundError):
        svc.update("nao-existe", name="Z")


def test_connection_update_remote_url(svc):
    a = svc.create("A")
    upd = svc.update(a.id, remote_url="https://github.com/acme/repo.git")
    assert upd.remote_url == "https://github.com/acme/repo.git"
    upd = svc.update(a.id, remote_url=None)
    assert upd.remote_url is None


def test_connection_delete(svc):
    conn = svc.create("A")
    assert svc.delete(conn.id) is True
    assert svc.delete(conn.id) is False
    assert conn.id not in [c.id for c in ConfigManager.load().connections]


def test_connection_delete_nao_apaga_a_pasta(svc):
    conn = svc.create("A")
    clone_path = ConfigManager.load().get_connection(conn.id).clone_path()
    assert clone_path.exists()
    svc.delete(conn.id)
    assert clone_path.exists()  # dado do usuário: não é apagado automaticamente


def test_connection_delete_da_default_passa_o_posto_para_outra(svc):
    a, b = svc.create("A"), svc.create("B")
    svc.set_default(a.id)
    assert svc.delete(a.id) is True
    assert ConfigManager.load().default == b.id
    assert svc.get(b.id).is_default is True


def test_connection_delete_da_unica_deixa_sem_padrao(svc):
    only = svc.create("Only")
    assert svc.delete(only.id) is True
    assert ConfigManager.load().default is None
    with pytest.raises(NoConnectionError):
        WorkspaceService().list()


def test_set_default_desabilitada_falha(svc):
    svc.create("A")
    b = svc.create("B", enabled=False)
    with pytest.raises(ValidationError):
        svc.set_default(b.id)
    with pytest.raises(NotFoundError):
        svc.set_default("nao-existe")


def test_workspace_fica_na_pasta_da_sua_conexao(svc):
    a = svc.create("A")
    b = svc.create("B")
    ws = WorkspaceService(connection_id=b.id).create("W")
    assert ws.id == "w"
    assert WorkspaceService().list() == []  # a padrão (A) não enxerga
    assert (Path(svc.get(b.id).path) / "w" / ".knowledge.yaml").is_file()
    assert a.is_default


def test_conexoes_ficam_no_json_com_o_remote_url(svc, tmp_path):
    remote = _bare_repo(tmp_path)
    svc.create("A", remote_url=remote, test=False)
    path = ConfigManager.CONNECTIONS_FILE
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["connections"][0]["remote_url"] == remote
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


# ---- health ---------------------------------------------------------------------------------


def test_health_sem_conexao_e_vazio(svc):
    assert svc.health() == []


def test_health_md_quebrado_aparece_em_parse_errors(svc):
    conn = svc.create("Local", test=False)
    folder = Path(conn.path)
    (folder / "w" / "p").mkdir(parents=True)
    (folder / "w" / "p" / "quebrado.md").write_text("---\nnao: [fecha\n---\ncorpo\n",
                                                    encoding="utf-8")
    [row] = svc.health()
    assert (row["name"], row["path"], row["ok"]) == ("Local", conn.path, True)
    assert [e["path"] for e in row["parse_errors"]] == ["w/p/quebrado.md"]
    assert row["parse_errors"][0]["error"]


def test_data_invalida_vai_para_parse_errors_e_offset_nao_derruba(svc):
    from datetime import datetime

    from knowledge_os.services.item_file import serialize_item

    conn = svc.create("Local", test=False)
    folder = Path(conn.path)
    (folder / "w" / "p").mkdir(parents=True)
    item = {"id": "8f3e2c0a-0000-0000-0000-000000000001", "type": "rule", "title": "T",
            "summary": "S", "content": "c", "status": "active", "origin": "agent",
            "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1)}
    raw = serialize_item(item, workspace_name="w", project_name="p", subject_name=None,
                         relations=[], tags=[])
    ok = raw.replace("created_at: '2026-01-01T00:00:00Z'",
                     "created_at: '2020-01-01T00:00:00+03:00'")
    assert ok != raw
    (folder / "w" / "p" / "ok.md").write_text(ok, encoding="utf-8")
    bad = raw.replace("created_at: '2026-01-01T00:00:00Z'", "created_at: lixo").replace(
        "8f3e2c0a-0000-0000-0000-000000000001", "8f3e2c0a-0000-0000-0000-000000000002")
    (folder / "w" / "p" / "ruim.md").write_text(bad, encoding="utf-8")
    [row] = svc.health()
    assert [e["path"] for e in row["parse_errors"]] == ["w/p/ruim.md"]


def test_health_pasta_sumida_ou_sem_git_nao_esta_ok(svc, tmp_path):
    a = svc.create("A", test=False)
    b = svc.create("B", test=False)
    Path(a.path).rename(tmp_path / "a-sumiu")
    (Path(b.path) / ".git").rename(Path(b.path) / "git-velho")
    rows = {r["name"]: r for r in svc.health()}
    assert rows["A"]["ok"] is False and rows["A"]["parse_errors"] == []
    assert rows["B"]["ok"] is False
