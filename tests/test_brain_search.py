"""Busca do segundo cérebro: PT-BR, relevância, escopo e itens inativos (plumb-brain T3)."""

from datetime import timedelta

import pytest

from knowledge_os.services.brain import utcnow
from knowledge_os.services.item_service import ItemService
from knowledge_os.storage.search import query_terms, stem, terms


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _mk(svc, ws, dm, **over):
    base = dict(
        workspace_id=ws.id, project_id=dm.id, type="knowledge", memory_class="longterm",
        title="Titulo", summary="Resumo", content="Conteudo",
    )
    base.update(over)
    return svc.create(**base)


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


def test_acha_sem_acento_e_no_plural(svc, sample_workspace, sample_project):
    it = _mk(svc, sample_workspace, sample_project, title="Migrações com Flyway")
    for q in ("migração", "migracao", "migrações", "MIGRAR"):
        assert [r["id"] for r in svc.search(sample_workspace.id, None, q)] == [it.id], q


def test_or_quando_and_nao_acha(svc, sample_workspace, sample_project):
    it = _mk(svc, sample_workspace, sample_project, title="Flyway", content="versionar o schema")
    assert [r["id"] for r in svc.search(sample_workspace.id, None, "flyway kubernetes")] == [it.id]


def test_relevancia_vence_importance(svc, sample_workspace, sample_project):
    alvo = _mk(svc, sample_workspace, sample_project, title="Cache com Redis",
               summary="TTL e invalidação no Redis", importance=1)
    _mk(svc, sample_workspace, sample_project, title="Deploy do backend",
        summary="pipeline", content="o deploy reinicia o redis", importance=10)
    assert svc.search(sample_workspace.id, None, "redis cache")[0]["id"] == alvo.id


def test_keywords_entram_na_busca(svc, sample_workspace, sample_project):
    it = _mk(svc, sample_workspace, sample_project, title="Valores monetários",
             keywords="dinheiro centavos BigDecimal")
    assert svc.search(sample_workspace.id, None, "centavos")[0]["id"] == it.id


def test_sem_workspace_busca_em_todos(svc):
    out = svc.save([
        {"workspace": "W1", "project": "D1", "type": "knowledge", "title": "Gotcha do Hibernate",
         "summary": "s", "content": "c"},
        {"workspace": "Outro", "project": "D2", "type": "knowledge",
         "title": "Hibernate no projeto novo", "summary": "s", "content": "c"},
    ])
    found = {r["id"] for r in svc.search(None, None, "hibernate")}
    assert found == {out[0]["id"], out[1]["id"]}


def test_resultado_traz_key_tipo_e_project(svc, sample_workspace, sample_project):
    _mk(svc, sample_workspace, sample_project, title="Regra X", key="regra/x", type="rule")
    (r,) = svc.search(sample_workspace.id, None, "regra")
    assert (r["key"], r["type"], r["project"]) == ("regra/x", "rule", sample_project.name)


def test_omite_substituidos_e_ephemeral_vencidos(svc, sample_workspace, sample_project,
                                                 data_dir):
    velho = _mk(svc, sample_workspace, sample_project, title="Deploy manual", status="superseded")
    eph = _mk(svc, sample_workspace, sample_project, title="Deploy rascunho",
              memory_class="ephemeral", ttl_days=1)
    path = data_dir / eph.path
    stamp = (utcnow() - timedelta(days=2)).isoformat() + "Z"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(eph.updated_at.isoformat() + "Z", stamp), encoding="utf-8")
    assert svc.search(sample_workspace.id, None, "deploy") == []
    todos = {r["id"] for r in svc.search(sample_workspace.id, None, "deploy",
                                          include_inactive=True)}
    assert todos == {velho.id, eph.id}


def test_ephemeral_vence_em_updated_at_mais_ttl(svc, sample_workspace, sample_project):
    eph = _mk(svc, sample_workspace, sample_project, memory_class="ephemeral", ttl_days=7)
    assert eph.expires_at == eph.updated_at + timedelta(days=7)
    assert timedelta(days=6) < eph.expires_at - utcnow() <= timedelta(days=7)
