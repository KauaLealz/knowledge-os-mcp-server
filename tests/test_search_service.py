"""`ItemService.search` e `get_many` (V2_MVP.md §4, §5): cadeia de alcance, filtros, grupos,
resultado explicado, sinais no ranking e contadores automáticos."""

import dataclasses
from datetime import timedelta

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.brain import Brain, meta_location, utcnow
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
    """W/P (repo ligado), W/Q e E/R, com o mesmo texto em scopes diferentes."""
    return {
        "p": _save(svc, "W", "P", key="rule/p"),
        "q_ws": _save(svc, "W", "Q", key="rule/q-ws", scope="workspace"),
        "q_scoped": _save(svc, "W", "Q", key="rule/q-scoped"),
        "e_global": _save(svc, "E", "R", key="rule/e-global", scope="global"),
        "e_scoped": _save(svc, "E", "R", key="rule/e-scoped"),
    }


def _ids(out):
    return [r["id"] for r in out["results"]]


def _age(item_id, **changes):
    brain = Brain()
    with brain.editing() as d:
        d.update(item_id, **changes)
        brain.commit(d, "envelhece")


# ---- alcance ----------------------------------------------------------------------------


def test_cadeia_de_alcance_em_ordem_com_where_e_scope(svc, world):
    out = svc.search("kubernetes", viewpoint=VP)
    assert _ids(out) == [world["p"], world["q_ws"], world["e_global"]]
    rows = out["results"]
    assert [r["where"] for r in rows] == ["W/P", "W/Q", "E/R"]
    assert [r["scope"] for r in rows] == ["scoped", "workspace", "global"]
    assert "suggestion" not in out


def test_scope_herdado_do_workspace_entra_no_alcance(svc, world):
    brain = Brain()
    with brain.editing() as d:
        d.set_meta(meta_location("e"), {"name": "E", "scope": "global"})
        brain.commit(d, "E global")
    found = set(_ids(svc.search("kubernetes", viewpoint=VP)))
    assert world["e_scoped"] in found


def test_pasta_nao_ligada_ve_so_globais_e_recebe_sugestao(svc, world):
    out = svc.search("kubernetes")
    assert _ids(out) == [world["e_global"]]
    assert 'repo(action="link"' in out["suggestion"]


def test_workspace_busca_o_workspace_inteiro_e_os_globais(svc, world):
    found = set(_ids(svc.search("kubernetes", workspace="W")))
    assert found == {world["p"], world["q_ws"], world["q_scoped"], world["e_global"]}


def test_everywhere_traz_tudo(svc, world):
    assert set(_ids(svc.search("kubernetes", everywhere=True))) == set(world.values())


def test_filtro_scope_global_lista_os_globais(svc, world):
    assert _ids(svc.search("", viewpoint=VP, scope=["global"])) == [world["e_global"]]


# ---- filtros ----------------------------------------------------------------------------


@pytest.fixture
def variados(svc):
    return {
        "sec": _save(svc, "W", "P", key="rule/sec", subtype="security", tags=["lgpd"],
                     origin="user", scope_paths=["src/payments/**"]),
        "howto": _save(svc, "W", "P", key="howto/x", type="howto", subtype="procedure"),
        "review": _save(svc, "W", "P", key="rule/rev", status="review", tags=["lgpd"]),
        "glob": _save(svc, "W", "P", key="rule/glob", scope="global", origin="code"),
    }


@pytest.mark.parametrize("filtro, esperado", [
    ({"types": ["howto"]}, {"howto"}),
    ({"subtypes": ["security"]}, {"sec"}),
    ({"status": ["review"]}, {"review"}),
    ({"tags": ["lgpd"]}, {"sec", "review"}),
    ({"origin": ["user"]}, {"sec"}),
    ({"origin": "code"}, {"glob"}),
    ({"scope": ["global"]}, {"glob"}),
    ({"paths": ["src/payments/a.py"], "types": ["rule"], "subtypes": ["security"]}, {"sec"}),
])
def test_filtros(svc, variados, filtro, esperado):
    out = svc.search("deploy", viewpoint=VP, **filtro)
    assert set(_ids(out)) == {variados[k] for k in esperado}


def test_paths_sem_consulta_exclui_quem_tem_scope_paths_de_outro_lugar(svc, variados):
    out = svc.search("", viewpoint=VP, paths=["docs/readme.md"], types=["rule", "howto"])
    assert variados["sec"] not in _ids(out) and variados["howto"] in _ids(out)


def test_paths_com_consulta_so_ordena_e_nao_esconde_o_achado_pelo_texto(svc, variados):
    out = svc.search("deploy", viewpoint=VP, paths=["docs/readme.md"])
    assert variados["sec"] in _ids(out) and variados["howto"] in _ids(out)


def test_paths_sobe_no_ranking_e_traz_excerpt(svc):
    plain = _save(svc, "W", "P", key="rule/plain")
    scoped = _save(svc, "W", "P", key="rule/scoped", scope_paths=["src/payments/**"])
    rows = svc.search("deploy", viewpoint=VP, paths=["src/payments/a.py"])["results"]
    assert [r["id"] for r in rows] == [scoped, plain]
    assert "path" in rows[0]["matched_in"] and rows[0]["scope_paths"] == ["src/payments/**"]
    assert rows[0]["excerpt"] == TEXT["content"]


def test_padrao_exclui_archived_e_vencidos_e_expired_os_mostra(svc):
    ok = _save(svc, "W", "P", key="rule/ok")
    _save(svc, "W", "P", key="rule/arq", status="archived")
    venc = _save(svc, "W", "P", key="rule/venc", ttl_days=1)
    _age(venc, updated_at=utcnow() - timedelta(days=2))
    assert _ids(svc.search("deploy", viewpoint=VP)) == [ok]
    rows = svc.search("deploy", viewpoint=VP, status=["expired"])["results"]
    assert [(r["id"], r["status"]) for r in rows] == [(venc, "expired")]


def test_review_vem_depois_e_marcado(svc):
    rev = _save(svc, "W", "P", key="rule/rev", status="review")
    ok = _save(svc, "W", "P", key="rule/ok")
    rows = svc.search("deploy", viewpoint=VP)["results"]
    assert [(r["id"], r["status"]) for r in rows] == [(ok, "active"), (rev, "review")]


# ---- formato ----------------------------------------------------------------------------


def test_resultado_explicado_sem_content(svc):
    _save(svc, "W", "P", key="rule/x", subtype="code")
    (row,) = svc.search("kubernetes", viewpoint=VP)["results"]
    assert set(row) == {"id", "key", "type", "subtype", "title", "summary", "scope", "where",
                        "status", "score", "matched_in", "snippet", "url"}
    assert row["matched_in"] == ["title"] and "Kubernetes" in row["snippet"]
    assert isinstance(row["score"], float)


def test_content_head(svc):
    _save(svc, "W", "P", key="rule/x")
    (row,) = svc.search("kubernetes", viewpoint=VP, content_head=8)["results"]
    assert row["content_head"] == "O deploy"


def test_queries_em_grupos_e_no_maximo_5(svc, world):
    out = svc.search(queries=["kubernetes", "inexistente"], viewpoint=VP)
    assert [g["query"] for g in out["groups"]] == ["kubernetes", "inexistente"]
    assert len(out["groups"][0]["results"]) == 3 and out["groups"][1]["results"] == []
    with pytest.raises(ValidationError, match="no máximo 5"):
        svc.search(queries=["a", "b", "c", "d", "e", "f"], viewpoint=VP)


def test_sem_consulta_com_repo_devolve_o_essencial_agrupado(svc):
    sec = _save(svc, "W", "P", key="rule/sec", subtype="security")
    regra = _save(svc, "W", "P", key="rule/code", subtype="code")
    ctx = _save(svc, "W", "P", key="context/x", type="context")
    spec = _save(svc, "W", "P", key="spec/x", type="spec", status="draft")
    _save(svc, "W", "P", key="spec/feita", type="spec", status="done")
    _save(svc, "W", "P", key="howto/x", type="howto")
    out = svc.search(viewpoint=VP)
    groups = {g["group"]: [r["id"] for r in g["results"]] for g in out["groups"]}
    assert list(groups) == ["seguranca", "regras", "contexto", "specs"]
    assert groups == {"seguranca": [sec], "regras": [regra], "contexto": [ctx],
                      "specs": [spec]}


# ---- sinais -----------------------------------------------------------------------------


def test_agent_com_helped_vem_antes_do_igual(svc):
    a = _save(svc, "W", "P", key="rule/a")
    b = _save(svc, "W", "P", key="rule/b")
    _age(b, updated_at=utcnow() - timedelta(days=1))  # sem sinal, `a` (mais novo) venceria
    for _ in range(3):
        local_state.count("teste", [b], "helped")
    assert _ids(svc.search("deploy", viewpoint=VP)) == [b, a]


def test_user_com_irrelevant_mantem_o_score(svc):
    a = _save(svc, "W", "P", key="rule/a", origin="user")
    b = _save(svc, "W", "P", key="rule/b", origin="user")
    for _ in range(5):
        local_state.count("teste", [b], "irrelevant")
        local_state.count("teste", [b], "shown")
    scores = {r["id"]: r["score"] for r in svc.search("deploy", viewpoint=VP)["results"]}
    # `b` foi mostrado 5 vezes (sobe nada) e marcado irrelevante 5 (não desce por ser user)
    assert scores[a] == pytest.approx(scores[b])


def test_agent_irrelevante_perde_peso(svc):
    a = _save(svc, "W", "P", key="rule/a")
    b = _save(svc, "W", "P", key="rule/b")
    _age(a, updated_at=utcnow() - timedelta(days=1))
    for _ in range(5):
        local_state.count("teste", [b], "irrelevant")
        local_state.count("teste", [b], "shown")
    rows = svc.search("deploy", viewpoint=VP)["results"]
    assert [r["id"] for r in rows] == [a, b]
    assert rows[1]["score"] == pytest.approx(rows[0]["score"] * 0.7)


def test_busca_soma_shown_e_vazia_vai_para_o_log(svc):
    a = _save(svc, "W", "P", key="rule/a")
    svc.search("deploy", viewpoint=VP)
    svc.search("deploy", viewpoint=VP)
    assert local_state.get_usage("teste")[a]["shown"] == 2
    assert local_state.get_usage("teste")[a]["opened"] == 0
    assert svc.search("zzzinexistente", viewpoint=VP)["results"] == []
    assert local_state.empty_searches("teste")[0]["query"] == "zzzinexistente"


def test_limit(svc):
    svc.save([{**TEXT, "key": f"rule/n{i}"} for i in range(5)], default_location=("W", "P"))
    assert len(svc.search("deploy", viewpoint=VP, limit=3)["results"]) == 3
    with pytest.raises(ValidationError, match="limit"):
        svc.search("deploy", viewpoint=VP, limit=0)


# ---- get_many ---------------------------------------------------------------------------


def test_get_many_resolve_pela_cadeia_e_soma_opened(svc, world):
    rows = svc.get_many(keys=["rule/e-global", "rule/q-scoped", "rule/p"], viewpoint=VP)
    assert rows[0]["id"] == world["e_global"] and rows[0]["where"] == "E/R"
    assert rows[0]["content"] == TEXT["content"] and rows[0]["scope"] == "global"
    assert rows[1] == {"key": "rule/q-scoped", "missing": True}  # fora do alcance
    assert rows[2]["id"] == world["p"]
    usage = local_state.get_usage("teste")
    assert usage[world["e_global"]]["opened"] == 1 and usage[world["p"]]["last_used_at"]


def test_get_many_por_id_e_em_workspace_project(svc, world):
    rows = svc.get_many(ids=[world["q_scoped"], "nao-existe"])
    assert rows[0]["id"] == world["q_scoped"] and rows[1] == {"id": "nao-existe",
                                                              "missing": True}
    (row,) = svc.get_many(keys=["rule/q-scoped"], workspace="W", project="Q")
    assert row["id"] == world["q_scoped"]


def test_get_many_no_maximo_20(svc):
    with pytest.raises(ValidationError, match="no máximo 20"):
        svc.get_many(keys=[f"rule/{i}" for i in range(21)], viewpoint=VP)


def test_get_many_traz_relacoes_e_campos_v2(svc):
    from knowledge_os.services.relation_service import RelationService

    a = _save(svc, "W", "P", key="rule/a", links=[{"title": "Doc", "url": "https://d.x"}])
    _save(svc, "W", "P", key="rule/b")
    RelationService().create([{"source": "rule/a", "type": "references", "target": "rule/b"}],
                             viewpoint=VP)
    (row,) = svc.get_many(ids=[a])
    assert row["relations"] == [{"type": "references", "target": "rule/b",
                                 "target_id": row["relations"][0]["target_id"]}]
    assert row["links"] == [{"title": "Doc", "url": "https://d.x"}]
    assert row["origin"] == "agent" and row["subtype"] is None
    assert row["created_at"].endswith("Z")


def test_get_ve_dataclass_view(svc):
    a = _save(svc, "W", "P", key="rule/a")
    item = svc.get(a)
    assert dataclasses.is_dataclass(item) and item.key == "rule/a"
    assert svc.get_by_key("w", "p", "rule/a").id == a
