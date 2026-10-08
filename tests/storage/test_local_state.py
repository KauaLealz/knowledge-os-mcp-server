"""Testes do estado local da máquina (storage/local_state.py)."""

import json

import knowledge_os.config as config
from knowledge_os.storage import local_state


def test_repos_ida_e_volta(_isolated_home):
    assert local_state.list_repos() == {}
    assert local_state.get_repo("r1") is None
    local_state.set_repo("r1", connection_id="c1", workspace="W", project="P")
    got = local_state.get_repo("r1")
    assert got["connection_id"] == "c1" and got["workspace"] == "W" and got["project"] == "P"
    assert got["created_at"] and got["updated_at"]
    criado = got["created_at"]
    local_state.set_repo("r1", connection_id="c2", workspace="W", project="Q")
    got = local_state.get_repo("r1")
    assert got["connection_id"] == "c2" and got["created_at"] == criado
    assert list(local_state.list_repos()) == ["r1"]
    assert (_isolated_home / "repos.json").is_file()
    assert local_state.delete_repo("r1") is True
    assert local_state.delete_repo("r1") is False
    assert local_state.list_repos() == {}


def test_home_trocado_em_teste(tmp_path, monkeypatch):
    outro = tmp_path / "outro-home"
    monkeypatch.setattr(config, "KNOWLEDGE_HOME", outro)
    local_state.set_repo("r", connection_id="c", workspace="W", project="P")
    assert (outro / "repos.json").is_file()


def test_repos_corrompido_nao_derruba_nem_apaga(_isolated_home):
    _isolated_home.mkdir(parents=True, exist_ok=True)
    arq = _isolated_home / "repos.json"
    arq.write_text("{nao é json", encoding="utf-8")
    assert local_state.list_repos() == {}
    assert local_state.get_repo("x") is None
    assert arq.read_text(encoding="utf-8") == "{nao é json"


def test_usage_conta_e_le(_isolated_home):
    assert local_state.get_usage("c1") == {}
    local_state.track("c1", ["a", "b"])
    local_state.track("c1", ["a"])
    uso = local_state.get_usage("c1")
    assert uso["a"]["uses"] == 2 and uso["b"]["uses"] == 1
    assert uso["a"]["last_used"]
    assert local_state.get_usage("c2") == {}
    dados = json.loads((_isolated_home / "usage" / "c1.json").read_text(encoding="utf-8"))
    assert dados["a"]["uses"] == 2


def test_usage_corrompido_e_falha_nao_levantam(_isolated_home, monkeypatch):
    pasta = _isolated_home / "usage"
    pasta.mkdir(parents=True)
    (pasta / "c1.json").write_text("[]", encoding="utf-8")
    assert local_state.get_usage("c1") == {}

    def falha(*_a, **_k):
        raise OSError("sem permissão")

    monkeypatch.setattr(local_state.os, "replace", falha)
    local_state.track("c1", ["a"])  # best-effort: não levanta
    assert local_state.track("c1", []) is None
