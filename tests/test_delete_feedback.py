"""`ItemService.delete` (candidatos, prévia, confirm) e `ItemService.feedback` (V2_MVP.md §6)."""

import subprocess
from datetime import timedelta

import pytest

from knowledge_os.exceptions import ValidationError
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


def test_candidatos_por_motivo_e_nunca_origin_user(svc):
    ids = {
        "expired": _save(svc, key="rule/venc", ttl_days=1),
        "archived_90d": _save(svc, key="rule/arq", status="archived"),
        "stale_review_14d": _save(svc, key="rule/rev", status="review"),
        "unused": _save(svc, key="rule/sem-uso"),
        "irrelevant": _save(svc, key="rule/irr"),
    }
    user = _save(svc, key="rule/user", status="archived", origin="user")
    _save(svc, key="rule/novo")  # recente: não é candidato
    recent_arch = _save(svc, key="rule/arq-recente", status="archived")
    usado = _save(svc, key="rule/usado")
    _edit(ids["expired"], updated_at=_old(2))
    _edit(ids["archived_90d"], updated_at=_old(91))
    _edit(ids["stale_review_14d"], updated_at=_old(15))
    _edit(ids["unused"], created_at=_old(120), updated_at=_old(120))
    _edit(user, updated_at=_old(200), created_at=_old(200))
    _edit(usado, created_at=_old(120), updated_at=_old(120))
    local_state.count("teste", [usado], "opened")
    for _ in range(3):
        local_state.count("teste", [ids["irrelevant"]], "irrelevant")
    local_state.count("teste", [ids["irrelevant"]], "helped")

    out = svc.delete(viewpoint=VP)
    got = {c["id"]: c["reason"] for c in out["candidates"]}
    assert got == {v: k for k, v in ids.items()}
    assert user not in got and recent_arch not in got and usado not in got
    assert all(set(c) == {"key", "id", "reason"} for c in out["candidates"])


def test_irrelevant_so_quando_supera_helped(svc):
    a = _save(svc, key="rule/a")
    for _ in range(3):
        local_state.count("teste", [a], "irrelevant")
        local_state.count("teste", [a], "helped")
    assert svc.delete(viewpoint=VP)["candidates"] == []


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
    RelationService().create([{"source": "rule/a", "type": "references", "target": "rule/b"}],
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


# ---- feedback ---------------------------------------------------------------------------


def test_helped_e_irrelevant_so_contam_sem_commit(svc, data_dir):
    a = _save(svc, key="rule/a")
    before = _log(data_dir)
    out = svc.feedback([{"key": "rule/a", "outcome": "helped"},
                        {"id": a, "outcome": "irrelevant", "query": "deploy"}], viewpoint=VP)
    assert out == {"applied": 2, "missing": []}
    usage = local_state.get_usage("teste")[a]
    assert (usage["helped"], usage["irrelevant"]) == (1, 1)
    assert _log(data_dir) == before


def test_feedback_repetido_no_lote_conta_uma_vez_e_applied_reflete(svc, data_dir):
    a = _save(svc, key="rule/a")
    b = _save(svc, key="rule/b")
    out = svc.feedback([{"key": "rule/a", "outcome": "helped"},
                        {"key": "rule/a", "outcome": "helped"},
                        {"id": a, "outcome": "helped"},
                        {"key": "rule/a", "outcome": "irrelevant"},
                        {"key": "rule/b", "outcome": "helped"}], viewpoint=VP)
    assert out == {"applied": 3, "missing": []}
    usage = local_state.get_usage("teste")
    assert (usage[a]["helped"], usage[a]["irrelevant"], usage[b]["helped"]) == (1, 1, 1)


@pytest.mark.parametrize("outcome", ["wrong", "outdated"])
def test_wrong_e_outdated_poem_em_review_com_nota_e_commit(svc, data_dir, outcome):
    a = _save(svc, key="rule/a")
    before = len(_log(data_dir))
    out = svc.feedback([{"key": "rule/a", "outcome": outcome, "note": "mudou para v2"}],
                       viewpoint=VP)
    assert out["applied"] == 1
    item = svc.get(a)
    assert item.status == "review"
    assert f"> Revisão {utcnow().date().isoformat()}: mudou para v2" in item.content
    assert len(_log(data_dir)) == before + 1
    assert local_state.get_usage("teste")[a][outcome] == 1


def test_verified_grava_data_e_commit_do_repo(svc, tmp_path):
    repo = tmp_path / "codigo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q",
                                 "--allow-empty", "-m", "x"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()
    a = _save(svc, key="rule/a")
    b = _save(svc, key="rule/b", status="review")
    svc.feedback([{"key": "rule/a", "outcome": "verified"}], viewpoint=VP, repo_path=str(repo))
    svc.feedback([{"key": "rule/b", "outcome": "verified"}], viewpoint=VP,
                 repo_path=str(tmp_path / "nao-e-git"))
    item_a, item_b = svc.get(a), svc.get(b)
    assert item_a.verified_at is not None and item_a.verified_commit == head
    assert item_b.verified_at is not None and item_b.verified_commit is None
    assert item_b.status == "review"  # verified não reativa


def test_feedback_key_inexistente_vai_para_missing(svc):
    _save(svc, key="rule/a")
    out = svc.feedback([{"key": "rule/a", "outcome": "helped"},
                        {"key": "rule/nao-existe", "outcome": "helped"}], viewpoint=VP)
    assert out == {"applied": 1, "missing": ["rule/nao-existe"]}


def test_feedback_outcome_invalido_lista_os_validos(svc):
    _save(svc, key="rule/a")
    with pytest.raises(ValidationError, match="helped, irrelevant, wrong, outdated, verified"):
        svc.feedback([{"key": "rule/a", "outcome": "otimo"}], viewpoint=VP)


def test_nota_em_item_sem_content_nao_deixa_linha_em_branco_no_inicio(svc):
    a = _save(svc, key="rule/vazio", content="")
    svc.feedback([{"key": "rule/vazio", "outcome": "wrong", "note": "mudou"}], viewpoint=VP)
    content = svc.get(a).content
    assert content.startswith("> Revisão ") and not content.startswith("\n")


def test_notas_seguidas_nao_acumulam_linhas_em_branco(svc):
    a = _save(svc, key="rule/duas")
    for note in ("primeira", "segunda"):
        svc.feedback([{"key": "rule/duas", "outcome": "wrong", "note": note}], viewpoint=VP)
    content = svc.get(a).content
    assert "primeira" in content and "segunda" in content
    assert "\n\n\n" not in content
    assert content.count("\n\n") == 1  # só a separação do corpo para a primeira nota
