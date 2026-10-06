"""Busca do segundo cérebro: PT-BR, relevância, escopo e itens inativos (plumb-brain T3)."""

from datetime import timedelta

import pytest
from sqlalchemy import DateTime, Engine, bindparam, text

from knowledge_os.db.dialects.sqlite import SQLiteDialect
from knowledge_os.db.models import Item, Project, Workspace
from knowledge_os.db.search_query import match_expressions, stem, terms
from knowledge_os.db.timeutil import utcnow
from knowledge_os.services.item_service import ItemService


@pytest.fixture
def svc(test_engine: Engine) -> ItemService:
    return ItemService(test_engine)


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


def test_consulta_vira_prefixos_and_e_or():
    assert match_expressions("migração banco") == ['"migr"* "banco"*', '"migr"* OR "banco"*']
    assert match_expressions("Flyway OR Liquibase") == ["Flyway OR Liquibase"]  # sintaxe FTS5
    assert match_expressions("") == [] and match_expressions("!!") == []
    assert match_expressions("UI")[0] == '"ui"*'  # termo curto não some


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


def test_sem_workspace_busca_em_todos(svc, test_session, sample_workspace, sample_project):
    outro = Workspace(id="w2", name="Outro")
    test_session.add(outro)
    test_session.flush()
    dm2 = Project(id="d2", workspace_id="w2", name="D2")
    test_session.add(dm2)
    test_session.commit()
    a = _mk(svc, sample_workspace, sample_project, title="Gotcha do Hibernate")
    b = _mk(svc, outro, dm2, title="Hibernate no projeto novo")
    found = {r["id"] for r in svc.search(None, None, "hibernate")}
    assert found == {a.id, b.id}


def test_resultado_traz_key_tipo_e_project(svc, sample_workspace, sample_project):
    _mk(svc, sample_workspace, sample_project, title="Regra X", key="regra/x", type="rule")
    (r,) = svc.search(sample_workspace.id, None, "regra")
    assert (r["key"], r["type"], r["project"]) == ("regra/x", "rule", sample_project.name)


def test_omite_substituidos_e_ephemeral_vencidos(
    svc, test_engine, sample_workspace, sample_project
):
    velho = _mk(svc, sample_workspace, sample_project, title="Deploy manual", status="superseded")
    eph = _mk(svc, sample_workspace, sample_project, title="Deploy rascunho",
              memory_class="ephemeral", ttl_days=1)
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE items SET expires_at = :p WHERE id = :i").bindparams(
                         bindparam("p", type_=DateTime)),
                     {"p": utcnow() - timedelta(days=1), "i": eph.id})
    assert svc.search(sample_workspace.id, None, "deploy") == []
    todos = {r["id"] for r in svc.search(sample_workspace.id, None, "deploy",
                                          include_inactive=True)}
    assert todos == {velho.id, eph.id}


def test_ephemeral_ganha_expires_at(svc, sample_workspace, sample_project):
    eph = _mk(svc, sample_workspace, sample_project, memory_class="ephemeral", ttl_days=7)
    assert eph.expires_at is not None
    assert timedelta(days=6) < eph.expires_at - utcnow() <= timedelta(days=7)


# ------------------------------------------------------------------ migração do índice


def test_indice_antigo_e_recriado_sem_perder_itens(test_engine):
    with test_engine.begin() as conn:
        for trig in ("items_fts_ai", "items_fts_ad", "items_fts_au"):
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trig}"))
        conn.execute(text("DROP TABLE items_fts"))
        conn.execute(text("CREATE VIRTUAL TABLE items_fts USING fts5(title, summary, content, "
                          "content='items', content_rowid='rowid')"))
        conn.execute(text("INSERT INTO workspaces (id, name, connection_id) "
                          "VALUES ('w', 'W', 'default')"))
        conn.execute(text("INSERT INTO projects (id, workspace_id, name) VALUES ('d', 'w', 'D')"))
        conn.execute(text(
            "INSERT INTO items (id, workspace_id, project_id, type, memory_class, title, summary, "
            "content, status, access_count) VALUES ('i1', 'w', 'd', 'knowledge', 'longterm', "
            "'Configuração do Redis', 's', 'c', 'active', 0)"))
    SQLiteDialect.create_fts_table(test_engine)
    with test_engine.connect() as conn:
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='items_fts'")).scalar()
    assert "keywords" in ddl and "remove_diacritics" in ddl
    assert [r["id"] for r in ItemService(test_engine).search("w", None, "configuracao")] == ["i1"]


def test_create_fts_table_idempotente(test_engine):
    SQLiteDialect.create_fts_table(test_engine)
    SQLiteDialect.create_fts_table(test_engine)
    with test_engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM sqlite_master WHERE name='items_fts'")).scalar()
    assert n == 1
    assert Item.__table__.c.item_key is not None
