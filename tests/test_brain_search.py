"""Busca do segundo cérebro pelo ItemService: PT-BR, relevância, alcance e itens vencidos.

O contrato completo da busca v2 está em test_search_service.py (serviço) e test_search_v2.py
(ranking)."""

from datetime import timedelta

import pytest

from knowledge_os.services.brain import utcnow
from knowledge_os.services.item_service import ItemService
from knowledge_os.storage.search import query_terms, stem, terms


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


VP = ("w", "p")


def _mk(svc, **over):
    base = dict(type="howto", title="Titulo", summary="Resumo", content="Conteudo")
    base.update(over)
    (row,) = svc.save([base], default_location=("W", "P"))
    return svc.get(row["id"])


def _ids(out):
    return [r["id"] for r in out["results"]]


# ------------------------------------------------------------------ normalização


def test_radical_ptbr_junta_singular_plural_e_verbo():
    assert stem("migracao") == stem("migracoes") == stem("migrar") == "migr"
    assert terms("Migrações de dados") == ["migr", "dado"]
    assert stem("idempotencia") == stem("idempotente") == "idempot"
    assert stem("pendencias") == stem("pendente") == "pend"
    assert stem("cliente") == "cliente"  # radical curto demais: não corta


def test_consulta_vira_prefixos_sem_sintaxe():
    assert query_terms("migração dados") == ["migr", "dado"]
    assert query_terms("Flyway OR Liquibase") == ["flyway", "or", "liquibase"]
    assert query_terms("") == [] and query_terms("!!") == []
    assert query_terms("UI") == ["ui"]  # termo curto não some


# ------------------------------------------------------------------ busca


def test_acha_sem_acento_e_no_plural(svc):
    it = _mk(svc, title="Migrações com Flyway")
    for q in ("migração", "migracao", "migrações", "MIGRAR"):
        assert _ids(svc.search(q, viewpoint=VP)) == [it.id], q


def test_or_quando_and_nao_acha(svc):
    it = _mk(svc, title="Flyway", content="versionar o schema")
    assert _ids(svc.search("flyway kubernetes", viewpoint=VP)) == [it.id]


def test_relevancia_vence_ordem_de_gravacao(svc):
    alvo = _mk(svc, title="Cache com Redis", summary="TTL e invalidação no Redis")
    _mk(svc, title="Deploy do backend", summary="pipeline", content="o deploy reinicia o redis")
    assert svc.search("redis cache", viewpoint=VP)["results"][0]["id"] == alvo.id


def test_keywords_entram_na_busca(svc):
    it = _mk(svc, title="Valores monetários", keywords="dinheiro centavos BigDecimal")
    assert svc.search("centavos", viewpoint=VP)["results"][0]["id"] == it.id


def test_everywhere_busca_em_todos(svc):
    out = svc.save([
        {"workspace": "W1", "project": "D1", "type": "howto", "title": "Gotcha do Hibernate",
         "summary": "s", "content": "c"},
        {"workspace": "Outro", "project": "D2", "type": "howto",
         "title": "Hibernate no projeto novo", "summary": "s", "content": "c"},
    ])
    found = set(_ids(svc.search("hibernate", everywhere=True)))
    assert found == {out[0]["id"], out[1]["id"]}


def test_resultado_traz_key_tipo_e_where(svc):
    _mk(svc, title="Regra X", key="rule/x", type="rule")
    (r,) = svc.search("regra", viewpoint=VP)["results"]
    assert (r["key"], r["type"], r["where"]) == ("rule/x", "rule", "W/P")


def test_omite_arquivados_e_vencidos(svc, data_dir):
    velho = _mk(svc, title="Deploy manual", status="archived")
    eph = _mk(svc, title="Deploy rascunho", ttl_days=1)
    path = data_dir / eph.path
    stamp = (utcnow() - timedelta(days=2)).isoformat() + "Z"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(eph.updated_at.isoformat() + "Z", stamp), encoding="utf-8")
    assert _ids(svc.search("deploy", viewpoint=VP)) == []
    todos = set(_ids(svc.search("deploy", viewpoint=VP, status=["archived", "expired"])))
    assert todos == {velho.id, eph.id}


def test_vencimento_e_updated_at_mais_ttl(svc):
    eph = _mk(svc, ttl_days=7)
    assert eph.expires_at == eph.updated_at + timedelta(days=7)
    assert timedelta(days=6) < eph.expires_at - utcnow() <= timedelta(days=7)
