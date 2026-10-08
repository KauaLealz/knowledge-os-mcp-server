"""Busca v2 (storage/search.py): campos novos, identificadores, alcance, paths, review, boost.

Registros montados à mão; o alcance, os filtros e os sinais são de quem chama (ItemService),
que entrega `Candidate(record, distance, boost)` prontos.
"""

from datetime import datetime

import pytest

from knowledge_os.storage.files import ItemRecord
from knowledge_os.storage.search import (
    Candidate,
    SearchIndex,
    paths_match,
    query_terms,
    search,
    tokenize,
)


def _rec(id_: str, **over) -> ItemRecord:
    base = dict(
        id=id_, key=None, workspace="W", project="P", subject=None, type="howto",
        subtype=None, scope=None, title="Titulo", status="active", tags=[], links=[],
        scope_paths=[], ttl_days=None, keywords=None, source=None, origin="agent",
        verified_at=None, verified_commit=None, created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1), relations=[], summary="Resumo", content="Conteudo",
    )
    base.update(over)
    return ItemRecord(**base)


def _c(*records: ItemRecord) -> list[Candidate]:
    return [Candidate(r) for r in records]


def _ids(hits) -> list[str]:
    return [h.record.id for h in hits]


# ------------------------------------------------------------------ campos e pesos


@pytest.mark.parametrize("field", ["title", "keywords", "summary", "content"])
def test_campos_de_texto_indexados(field):
    alvo = _rec("a", **{field: "observabilidade"})
    hits = search(_c(alvo, _rec("b")), "observabilidade", 10)
    assert _ids(hits) == ["a"]
    assert field in hits[0].matched_in


def test_titulo_pesa_mais_que_content():
    corpo = _rec("corpo", title="Outra", content="grafana")
    titulo = _rec("titulo", title="Grafana", content="nada")
    hits = search(_c(corpo, titulo), "grafana", 10)
    assert _ids(hits) == ["titulo", "corpo"]
    assert hits[0].matched_in == ["title"]
    assert hits[1].matched_in == ["content"]


def test_termo_em_mais_da_metade_do_acervo_ainda_ranqueia_pelos_campos():
    # 6 itens, "grafana" em 4: o idf clássico zeraria a relevância; o do Lucene não.
    # O do título é o mais antigo, para que só o campo (e não o desempate) o ponha na frente.
    titulo = _rec("titulo", title="Grafana", content="nada", updated_at=datetime(2025, 1, 1))
    corpos = [_rec(f"corpo{i}", title="Outra", content="grafana") for i in range(3)]
    sem = [_rec("x1"), _rec("x2")]
    hits = search(_c(*corpos, titulo, *sem), "grafana", 10)
    assert _ids(hits)[0] == "titulo"
    assert sorted(_ids(hits)[1:]) == ["corpo0", "corpo1", "corpo2"]
    assert hits[0].score > hits[1].score > 0.01


def test_tag_e_subtipo_achados_por_texto():
    tag = _rec("tag", tags=["lgpd"])
    sub = _rec("sub", type="rule", subtype="decision")
    hits = search(_c(tag, sub, _rec("nada")), "lgpd", 10)
    assert _ids(hits) == ["tag"] and hits[0].matched_in == ["tags"]
    hits = search(_c(tag, sub, _rec("nada")), "decision", 10)
    assert _ids(hits) == ["sub"] and hits[0].matched_in == ["subtype"]


def test_snippet_curto_com_o_termo():
    texto = ("palavra " * 60) + "kubernetes no meio " + ("outra " * 60)
    (hit,) = search(_c(_rec("a", content=texto)), "kubernetes", 10)
    assert "kubernetes" in hit.snippet
    assert len(hit.snippet) <= 160
    assert hit.excerpt is None


def test_snippet_vem_do_primeiro_campo_que_casou():
    (hit,) = search(_c(_rec("a", title="Deploy no Kubernetes", content="kubernetes x")),
                    "kubernetes", 10)
    assert hit.snippet == "Deploy no Kubernetes"
    assert hit.matched_in == ["title", "content"]


# ------------------------------------------------------------------ identificadores


def test_tokeniza_identificadores():
    assert tokenize("ItemService.saveBatch") == [
        "itemservice", "item", "service", "savebatch", "save", "batch"]
    assert tokenize("ERR_CONN_42") == ["err_conn_42", "err", "conn", "42"]
    assert tokenize("Migração simples") == ["migracao", "simples"]


@pytest.mark.parametrize("q", ["save batch", "saveBatch", "ItemService.saveBatch", "savebatch"])
def test_identificador_achado_pelas_partes_e_inteiro(q):
    alvo = _rec("a", content="Chame ItemService.saveBatch para gravar em lote")
    outro = _rec("b", content="Salvar item avulso")
    assert _ids(search(_c(alvo, outro), q, 10)) == ["a"]


def test_codigo_de_erro_achado_como_esta():
    alvo = _rec("a", title="Timeout no banco", content="O erro ERR_CONN_42 aparece no pool")
    vizinho = _rec("b", title="Outro erro", content="O erro ERR_AUTH_7 aparece no login")
    assert _ids(search(_c(alvo, vizinho), "ERR_CONN_42", 10)) == ["a"]


def test_consulta_recebe_o_mesmo_tratamento():
    assert query_terms("saveBatch") == ["savebatch", "save", "batch"]
    assert query_terms("ERR_CONN_42") == ["err_conn_42", "err", "conn", "42"]


# ------------------------------------------------------------------ alcance, review, boost


def test_distancia_ordena_igual_texto():
    proj = _rec("proj", title="Retry exponencial")
    ws = _rec("ws", title="Retry exponencial")
    glob = _rec("glob", title="Retry exponencial")
    cands = [Candidate(glob, distance=0.7), Candidate(ws, distance=0.85), Candidate(proj)]
    hits = search(cands, "retry", 10)
    assert _ids(hits) == ["proj", "ws", "glob"]
    assert hits[1].score == pytest.approx(hits[0].score * 0.85)
    assert hits[2].score == pytest.approx(hits[0].score * 0.7)


def test_review_perde_peso_e_fica_depois_do_igual():
    rev = _rec("rev", title="Cache de sessao", status="review")
    ativo = _rec("ativo", title="Cache de sessao")
    hits = search(_c(rev, ativo), "cache", 10)
    assert _ids(hits) == ["ativo", "rev"]
    assert hits[1].score == pytest.approx(hits[0].score * 0.6)


def test_boost_multiplica():
    a, b = _rec("a", title="Fila de eventos"), _rec("b", title="Fila de eventos")
    hits = search([Candidate(a), Candidate(b, boost=1.2)], "fila", 10)
    assert _ids(hits) == ["b", "a"]
    assert hits[0].score == pytest.approx(hits[1].score * 1.2)


# ------------------------------------------------------------------ paths


def test_paths_match_glob():
    rec = _rec("a", scope_paths=["src/payments/**", "docs/*.md"])
    assert paths_match(rec, ["src/payments/a.py"])
    assert paths_match(rec, ["src/payments/deep/x/b.py"])
    assert paths_match(rec, ["./src\\payments\\a.py"])
    assert paths_match(rec, ["docs/api.md"])
    assert not paths_match(rec, ["docs/sub/api.md"])
    assert not paths_match(rec, ["src/orders/a.py"])
    assert not paths_match(_rec("b"), ["src/payments/a.py"])
    assert not paths_match(rec, [])


def test_paths_sobe_no_ranking_e_traz_excerpt():
    longo = " ".join(f"palavra{i}" for i in range(200))
    com = _rec("com", title="Idempotencia no webhook", scope_paths=["src/payments/**"],
               content=longo)
    sem = _rec("sem", title="Idempotencia no webhook", content=longo)
    hits = search(_c(sem, com), "idempotencia", 10, paths=["src/payments/a.py"])
    assert _ids(hits) == ["com", "sem"]
    assert hits[0].score == pytest.approx(hits[1].score * 1.5)
    assert "path" in hits[0].matched_in and "path" not in hits[1].matched_in
    assert hits[0].excerpt and len(hits[0].excerpt) <= 600
    assert longo.startswith(hits[0].excerpt)
    assert not hits[0].excerpt.endswith(" ")
    assert longo[len(hits[0].excerpt)] == " "  # cortado em limite de palavra
    assert hits[1].excerpt is None


def test_excerpt_curto_vem_inteiro():
    rec = _rec("a", title="Regra", scope_paths=["src/**"], content="Use Decimal.")
    (hit,) = search(_c(rec), "regra", 10, paths=["src/x.py"])
    assert hit.excerpt == "Use Decimal."


# ------------------------------------------------------------------ sem consulta


def test_sem_consulta_ordena_por_distancia_paths_e_updated_at():
    velho = _rec("velho", updated_at=datetime(2026, 1, 1))
    novo = _rec("novo", updated_at=datetime(2026, 3, 1))
    longe = _rec("longe", updated_at=datetime(2026, 9, 1))
    casado = _rec("casado", scope_paths=["src/**"], updated_at=datetime(2025, 1, 1))
    cands = [Candidate(velho), Candidate(longe, distance=0.7), Candidate(novo),
             Candidate(casado, distance=0.85)]
    hits = search(cands, "", 10, paths=["src/a.py"])
    # casado: 0.85 × 1.5 = 1.275; novo/velho: 1.0 (desempate updated_at); longe: 0.7
    assert _ids(hits) == ["casado", "novo", "velho", "longe"]
    assert hits[0].matched_in == ["path"] and hits[0].excerpt == "Conteudo"
    assert hits[1].matched_in == [] and hits[1].excerpt is None
    assert [h.score for h in hits] == pytest.approx([1.275, 1.0, 1.0, 0.7])


def test_sem_consulta_review_e_boost():
    rev = _rec("rev", status="review")
    ok = _rec("ok")
    hot = _rec("hot")
    hits = search([Candidate(rev), Candidate(ok), Candidate(hot, boost=1.3)], "  ", 10)
    assert _ids(hits) == ["hot", "ok", "rev"]


# ------------------------------------------------------------------ AND/OR e stopwords


def test_and_com_queda_para_or():
    ambos = _rec("ambos", title="Flyway kubernetes")
    um = _rec("um", title="Flyway")
    outro = _rec("outro", title="Kubernetes")
    assert _ids(search(_c(ambos, um, outro), "flyway kubernetes", 10)) == ["ambos"]
    assert set(_ids(search(_c(um, outro), "flyway kubernetes", 10))) == {"um", "outro"}


def test_consulta_so_de_stopwords_usa_as_palavras():
    alvo = _rec("a", title="Para de vez")
    assert query_terms("para de") == ["para", "de"]
    assert _ids(search(_c(alvo, _rec("b", title="Outra")), "para de", 10)) == ["a"]


# ------------------------------------------------------------------ índice incremental


def test_indice_incremental_mantem_estatisticas():
    a = _rec("a", title="Redis cache", content="ttl curto")
    b = _rec("b", title="Redis", content=" ".join(["texto"] * 50))
    idx = SearchIndex()
    idx.add(a)
    idx.add(b)
    assert len(idx) == 2 and "b" in idx
    idx.remove("b")
    assert "b" not in idx
    fresh = SearchIndex()
    fresh.add(a)
    via_inc = search(_c(a), "redis", 10, index=idx)
    via_novo = search(_c(a), "redis", 10, index=fresh)
    assert via_inc[0].score == pytest.approx(via_novo[0].score)
    idx.add(_rec("a", title="Outro assunto", content="nada"))
    assert search(_c(a), "redis", 10, index=idx) == []
