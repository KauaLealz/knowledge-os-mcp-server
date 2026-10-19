"""`ItemService.delete` v6: candidatos de limpeza (tag `archived` com 90d, ou nunca usado com
90d), prévia e confirm. Não há mais feedback no v6 (o agente ajusta ou apaga o item)."""

import subprocess
from datetime import timedelta

import pytest

from knowledge_os.services.brain import Brain, utcnow
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.storage import local_state

VP = ("w", "p")
TEXT = {"type": "rule", "title": "Regra", "summary": "s", "content": "corpo"}


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _save(svc, **entry):
    return svc.save([{**TEXT, **entry}], default_location=("W", "P"))[0]["id"]


def _edit(item_id, **changes):
    brain = Brain()
    with brain.editing() as d:
        d.update(item_id, **changes)
        brain.commit(d, "ajuste de teste")


def _log(data_dir):
    return subprocess.run(["git", "log", "--format=%s"], cwd=data_dir, capture_output=True,
                          text=True, check=True).stdout.splitlines()


def _old(days):
    return utcnow() - timedelta(days=days)


# ---- candidatos -------------------------------------------------------------------------


def test_candidatos_por_motivo(svc):
    arch = _save(svc, key="rule/arq", tags=["archived"])
    unused = _save(svc, key="rule/sem-uso")
    _save(svc, key="rule/novo")  # recente: não é candidato
    recent_arch = _save(svc, key="rule/arq-recente", tags=["archived"])
    usado = _save(svc, key="rule/usado")
    _edit(arch, updated_at=_old(91))
    _edit(unused, created_at=_old(120), updated_at=_old(120))
    _edit(usado, created_at=_old(120), updated_at=_old(120))
    local_state.count("teste", [usado], "opened")

    out = svc.delete(viewpoint=VP)
    got = {c["id"]: c["reason"] for c in out["candidates"]}
    assert got == {arch: "archived", unused: "unused"}
    assert recent_arch not in got and usado not in got
    assert all(set(c) == {"key", "id", "reason"} for c in out["candidates"])


# ---- prévia e confirm -------------------------------------------------------------------


def test_previa_nao_apaga(svc, data_dir):
    a = _save(svc, key="rule/a")
    out = svc.delete(keys=["rule/a", "rule/nao-existe"], viewpoint=VP)
    assert out["status"] == "preview"
    assert [(i["id"], i["key"]) for i in out["items"]] == [(a, "rule/a")]
    assert out["missing"] == ["rule/nao-existe"]
    assert svc.get(a).id == a


def test_confirm_apaga_item_e_relacoes_num_commit(svc, data_dir):
    a = _save(svc, key="rule/a")
    b = _save(svc, key="rule/b")
    RelationService().create([{"source": "rule/a", "type": "relates_to", "target": "rule/b"}],
                             viewpoint=VP)
    before = len(_log(data_dir))
    out = svc.delete(keys=["rule/b"], viewpoint=VP, confirm=True)
    assert out == {"status": "deleted", "ids": [b]}
    log = _log(data_dir)
    assert len(log) == before + 1 and "remove" in log[0]
    assert not (data_dir / "w" / "p" / "rule" / "b.md").exists()
    text = (data_dir / "w" / "p" / "rule" / "a.md").read_text(encoding="utf-8")
    assert "rule/b" not in text
    assert svc.get(a).id == a


def test_confirm_por_id(svc):
    a = _save(svc, key="rule/a")
    assert svc.delete(ids=[a], confirm=True)["ids"] == [a]
    assert svc.get_many(ids=[a]) == [{"id": a, "missing": True}]


def test_remove_um_item_pela_api_fina(svc):
    a = _save(svc, key="rule/a")
    assert svc.remove(a) is True
    assert svc.get_many(ids=[a]) == [{"id": a, "missing": True}]
