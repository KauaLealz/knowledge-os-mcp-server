"""Alcance por hierarquia (v6): substitui o antigo sistema de scope. Um item vale onde mora na
árvore workspace → project → subject e em tudo abaixo; `reach`/`reaches`/`reach_distance`/
`resolve_key`/`where` no Snapshot."""

from datetime import datetime

from knowledge_os.services.brain import Snapshot
from knowledge_os.storage.files import ItemRecord


def _rec(id_, workspace="W", project="P", subject=None, **over) -> ItemRecord:
    base = dict(
        id=id_, key=f"rule/{id_}", workspace=workspace, project=project, subject=subject,
        type="rule", title=id_, tags=[], links=[],
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        summary="s", content="",
    )
    base.update(over)
    return ItemRecord(**base)


def _snap():
    return Snapshot({
        "w": _rec("w", project=None),            # nível do workspace
        "p": _rec("p"),                          # nível do project
        "s": _rec("s", subject="git"),           # nível do subject
        "other": _rec("other", project="Q"),     # outro project do mesmo workspace
    }, {})


def test_reaches_sobe_a_hierarquia():
    snap = _snap()
    # Do subject git enxerga workspace + project + subject daquele caminho.
    assert snap.reaches(snap.get("w"), "w", "p", "git")
    assert snap.reaches(snap.get("p"), "w", "p", "git")
    assert snap.reaches(snap.get("s"), "w", "p", "git")
    # Item de outro project não é alcançado de P.
    assert not snap.reaches(snap.get("other"), "w", "p")
    # Item do workspace alcança qualquer project.
    assert snap.reaches(snap.get("w"), "w", "qualquer")


def test_reach_distance_mais_proximo_primeiro():
    snap = _snap()
    d_sub = snap.reach_distance(snap.get("s"), "w", "p", "git")
    d_proj = snap.reach_distance(snap.get("p"), "w", "p", "git")
    d_ws = snap.reach_distance(snap.get("w"), "w", "p", "git")
    assert d_sub < d_proj < d_ws  # subject mais perto que project mais perto que workspace


def test_reach_lista_do_mais_proximo():
    snap = _snap()
    ids = [r.id for r, _d in snap.reach("w", "p", "git")]
    assert ids[0] == "s"  # o do subject vem primeiro
    assert set(ids) == {"w", "p", "s"} and "other" not in ids


def test_resolve_key_na_cadeia():
    snap = _snap()
    assert snap.resolve_key("rule/p", "w", "p").id == "p"
    assert snap.resolve_key("rule/w", "w", "p").id == "w"
    assert snap.resolve_key("rule/other", "w", "p") is None  # fora do alcance


def test_where_descreve_onde_mora():
    snap = _snap()
    assert snap.where(snap.get("s"))  # alguma descrição de onde o item vive
