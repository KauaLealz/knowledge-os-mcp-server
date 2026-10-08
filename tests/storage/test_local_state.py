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


def _em_paralelo(alvo, n: int = 8) -> None:
    import threading

    barreira = threading.Barrier(n)

    def corre(i: int) -> None:
        barreira.wait()
        alvo(i)

    threads = [threading.Thread(target=corre, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_track_concorrente_nao_perde_uso(_isolated_home):
    def usa(_i: int) -> None:
        for _ in range(15):
            local_state.track("c1", ["item-1"])

    _em_paralelo(usa)
    assert local_state.get_usage("c1")["item-1"]["uses"] == 8 * 15


def test_set_repo_concorrente_nao_perde_ligacao(_isolated_home):
    def liga(i: int) -> None:
        for j in range(5):
            local_state.set_repo(f"repo-{i}-{j}", connection_id="c", workspace="W", project="P")

    _em_paralelo(liga)
    assert len(local_state.list_repos()) == 8 * 5


def test_escritas_usam_a_trava_entre_processos(_isolated_home, monkeypatch):
    from contextlib import contextmanager

    usadas: list[str] = []

    @contextmanager
    def trava(root, *a, **k):
        usadas.append(str(root))
        yield

    monkeypatch.setattr(local_state, "folder_lock", trava)
    local_state.set_repo("r", connection_id="c", workspace="W", project="P")
    local_state.delete_repo("r")
    local_state.track("c1", ["x"])
    assert len(usadas) == 3
