"""`ItemService.search` e `get_many` (v6): alcance por hierarquia, filtros, grupos, resultado
explicado, sinais de uso no ranking e contadores automáticos."""

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_service import ItemService
from knowledge_os.storage import local_state

VP = ("w", "p")
TEXT = {"type": "rule", "title": "Deploy no Kubernetes", "summary": "Como o deploy roda",
        "content": "O deploy usa helm no cluster."}


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _save(svc, ws, pj, **entry):
    return svc.save([{**TEXT, **entry}], default_location=(ws, pj))[0]["id"]


@pytest.fixture
def world(svc):
    """O mesmo texto em W/P (repo ligado), W/Q (outro project) e E/R (outro workspace)."""
    return {
        "p": _save(svc, "W", "P", key="rule/p"),
        "q": _save(svc, "W", "Q", key="rule/q"),
        "e": _save(svc, "E", "R", key="rule/e"),
    }


def _ids(out):
    return [r["id"] for r in out["results"]]


# ---- alcance (hierarquia) ----------------------------------------------------------------


def test_viewpoint_ve_so_o_proprio_project(svc, world):
    out = svc.search("kubernetes", viewpoint=VP)
    assert _ids(out) == [world["p"]]
    assert out["results"][0]["where"] == "W/P"
    assert "suggestion" not in out


def test_workspace_busca_o_workspace_inteiro(svc, world):
    assert set(_ids(svc.search("kubernetes", workspace="W"))) == {world["p"], world["q"]}


def test_everywhere_traz_tudo(svc, world):
    assert set(_ids(svc.search("kubernetes", everywhere=True))) == set(world.values())


def test_pasta_nao_ligada_nao_acha_e_recebe_sugestao(svc, world):
    out = svc.search("kubernetes")
    assert _ids(out) == []
    assert 'repo(action="link"' in out["suggestion"]


# ---- filtros -----------------------------------------------------------------------------


@pytest.fixture
def variados(svc):
    return {
        "sec": _save(svc, "W", "P", key="rule/sec", tags=["security", "lgpd"],
                     links=[{"path": "src/payments/**"}]),
        "howto": _save(svc, "W", "P", key="howto/x", type="howto"),
        "lgpd2": _save(svc, "W", "P", key="rule/rev", tags=["lgpd"]),
    }


@pytest.mark.parametrize("filtro, esperado", [
    ({"types": ["howto"]}, {"howto"}),
    ({"tags": ["security"]}, {"sec"}),
    ({"tags": ["lgpd"]}, {"sec", "lgpd2"}),
    ({"paths": ["src/payments/a.py"], "types": ["rule"], "tags": ["security"]}, {"sec"}),
])
def test_filtros(svc, variados, filtro, esperado):
    out = svc.search("deploy", viewpoint=VP, **filtro)
    assert set(_ids(out)) == {variados[k] for k in esperado}


def test_padrao_exclui_archived_e_a_tag_os_mostra(svc):
    ok = _save(svc, "W", "P", key="rule/ok")
    arq = _save(svc, "W", "P", key="rule/arq", tags=["archived"])
    assert _ids(svc.search("deploy", viewpoint=VP)) == [ok]
    assert set(_ids(svc.search("deploy", viewpoint=VP, tags=["archived"]))) == {arq}


# ---- paths -------------------------------------------------------------------------------


def test_paths_sobe_no_ranking_e_traz_excerpt(svc):
    plain = _save(svc, "W", "P", key="rule/plain")
    com = _save(svc, "W", "P", key="rule/com", links=[{"path": "src/payments/**"}])
    rows = svc.search("deploy", viewpoint=VP, paths=["src/payments/a.py"])["results"]
    assert [r["id"] for r in rows] == [com, plain]
    assert "path" in rows[0]["matched_in"]
    assert rows[0]["excerpt"] == TEXT["content"]


# ---- formato -----------------------------------------------------------------------------


def test_resultado_explicado_sem_content(svc):
    _save(svc, "W", "P", key="rule/x")
    (row,) = svc.search("kubernetes", viewpoint=VP)["results"]
    assert set(row) == {"id", "key", "type", "title", "summary", "where", "score",
                        "matched_in", "snippet", "url"}
    assert row["matched_in"] == ["title"] and "Kubernetes" in row["snippet"]
    assert isinstance(row["score"], float)


def test_content_head(svc):
    _save(svc, "W", "P", key="rule/x")
    (row,) = svc.search("kubernetes", viewpoint=VP, content_head=8)["results"]
    assert row["content_head"] == "O deploy"


def test_queries_em_grupos_e_no_maximo_5(svc, world):
    out = svc.search(queries=["kubernetes", "inexistente"], viewpoint=VP)
    assert [g["query"] for g in out["groups"]] == ["kubernetes", "inexistente"]
    assert len(out["groups"][0]["results"]) == 1 and out["groups"][1]["results"] == []
    with pytest.raises(ValidationError, match="no máximo 5"):
        svc.search(queries=["a", "b", "c", "d", "e", "f"], viewpoint=VP)


def test_sem_consulta_com_repo_devolve_o_essencial_agrupado(svc):
    sec = _save(svc, "W", "P", key="rule/sec", tags=["security"])
    regra = _save(svc, "W", "P", key="rule/code")
    ctx = _save(svc, "W", "P", key="context/x", type="context")
    work = _save(svc, "W", "P", key="work/x", type="work", tags=["active"])
    out = svc.search(viewpoint=VP)
    groups = {g["group"]: [r["id"] for r in g["results"]] for g in out["groups"]}
    assert list(groups) == ["seguranca", "regras", "contexto", "specs"]
    assert groups == {"seguranca": [sec], "regras": [regra], "contexto": [ctx],
                      "specs": [work]}


# ---- sinais de uso -----------------------------------------------------------------------


def test_abrir_um_item_o_impulsiona_no_ranking(svc):
    a = _save(svc, "W", "P", key="rule/a")
    b = _save(svc, "W", "P", key="rule/b")
    for _ in range(20):
        local_state.count("teste", [b], "opened")
    rows = svc.search("deploy", viewpoint=VP)["results"]
    assert [r["id"] for r in rows] == [b, a]


def test_busca_soma_shown_e_vazia_vai_para_o_log(svc):
    a = _save(svc, "W", "P", key="rule/a")
    svc.search("deploy", viewpoint=VP)
    svc.search("deploy", viewpoint=VP)
    assert local_state.get_usage("teste")[a]["shown"] == 2
    assert local_state.get_usage("teste")[a].get("opened", 0) == 0
    assert svc.search("zzzinexistente", viewpoint=VP)["results"] == []
    assert local_state.empty_searches("teste")[0]["query"] == "zzzinexistente"


def test_limit(svc):
    svc.save([{**TEXT, "key": f"rule/n{i}"} for i in range(5)], default_location=("W", "P"))
    assert len(svc.search("deploy", viewpoint=VP, limit=3)["results"]) == 3
    with pytest.raises(ValidationError, match="limit"):
        svc.search("deploy", viewpoint=VP, limit=0)


# ---- get_many ----------------------------------------------------------------------------


def test_get_many_por_key_no_project_e_por_id(svc, world):
    got = svc.get_many(keys=["rule/p"], ids=[world["q"]], viewpoint=VP)
    achados = [g for g in got if not g.get("missing")]
    assert {g["id"] for g in achados} == {world["p"], world["q"]}


def test_get_many_conta_opened(svc):
    a = _save(svc, "W", "P", key="rule/a")
    svc.get_many(keys=["rule/a"], viewpoint=VP)
    assert local_state.get_usage("teste")[a]["opened"] == 1
