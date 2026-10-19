"""Estado local de sinais (`storage/local_state.py`): contadores por item e buscas vazias.

Fica fora do git, em `<home>/usage/<conn>.json` e `<home>/searches/<conn>.jsonl`.
"""

import json
import threading

from knowledge_os.storage import local_state


def _usage_file(home, cid="teste"):
    return home / "usage" / f"{cid}.json"


def test_shown_opened_e_last_used_at_somam(_isolated_home):
    local_state.count("teste", ["a", "b"], "shown")
    local_state.count("teste", ["a"], "shown")
    local_state.track("teste", ["a"])  # assinatura antiga: soma `opened`
    usage = local_state.get_usage("teste")
    assert usage["a"]["shown"] == 2 and usage["b"]["shown"] == 1
    assert usage["a"]["opened"] == 1 and usage["b"]["opened"] == 0
    assert usage["a"]["last_used_at"] and usage["b"]["last_used_at"] is None
    for name in ("helped", "wrong", "outdated", "irrelevant", "verified"):
        assert usage["a"][name] == 0


def test_helped_e_irrelevant_sobem_sem_git(_isolated_home, conn, data_dir):
    local_state.count("teste", ["a"], "helped")
    local_state.count("teste", ["a"], "irrelevant")
    local_state.count("teste", ["a"], "irrelevant")
    usage = local_state.get_usage("teste")["a"]
    assert (usage["helped"], usage["irrelevant"]) == (1, 2)
    assert _usage_file(_isolated_home).is_file()
    assert not (data_dir / ".git").exists()  # nada foi para a pasta da conexão


def test_campo_desconhecido_e_ignorado_sem_derrubar(_isolated_home):
    local_state.count("teste", ["a"], "inventado")
    assert local_state.get_usage("teste") == {}


def test_formato_antigo_e_lido_e_regravado_no_novo(_isolated_home):
    path = _usage_file(_isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"a": {"uses": 4, "last_used": "2026-01-02T03:04:05Z"}}),
                    encoding="utf-8")
    usage = local_state.get_usage("teste")["a"]
    assert usage["opened"] == 4 and usage["last_used_at"] == "2026-01-02T03:04:05Z"
    local_state.count("teste", ["a"], "shown")
    raw = json.loads(path.read_text(encoding="utf-8"))["a"]
    assert raw["opened"] == 4 and raw["shown"] == 1
    assert "uses" not in raw and "last_used" not in raw


def test_busca_vazia_registrada_e_agregada(_isolated_home):
    local_state.log_empty_search("teste", "kafka retry")
    local_state.log_empty_search("teste", "  Kafka Retry ")
    local_state.log_empty_search("teste", "flyway")
    local_state.log_empty_search("teste", "   ")  # vazia: não conta
    lines = (_isolated_home / "searches" / "teste.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert set(json.loads(lines[0])) == {"ts", "query"}
    agg = local_state.empty_searches("teste")
    assert [(e["query"], e["count"]) for e in agg] == [("kafka retry", 2), ("flyway", 1)]
    assert all(e["last_at"] for e in agg)
    assert local_state.empty_searches("outra") == []


def test_duas_threads_nao_perdem_contagem(_isolated_home):
    def worker():
        for _ in range(25):
            local_state.count("teste", ["a"], "shown")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert local_state.get_usage("teste")["a"]["shown"] == 50
