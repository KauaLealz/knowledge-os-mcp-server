"""Projetos e pacote de contexto do segundo cérebro (plumb-brain T5)."""

import subprocess

import pytest
from sqlalchemy import Engine

from knowledge_os.services.context_service import ContextService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.project_service import ProjectService, normalize_remote, project_key

BASE = dict(memory_class="longterm", summary="resumo", content="corpo")


@pytest.mark.parametrize("remote", [
    "git@github.com:KauaLealz/projpro.git",
    "https://github.com/KauaLealz/projpro",
    "https://token@github.com/kaualealz/projpro.git/",
    "ssh://git@github.com/KauaLealz/projpro.git",
])
def test_remote_normalizado(remote):
    assert normalize_remote(remote) == "github.com/kaualealz/projpro"


def test_chave_de_pasta_com_e_sem_remote(tmp_path):
    repo = tmp_path / "Repo"
    (repo / "src" / "deep").mkdir(parents=True)
    if subprocess.run(["git", "init", "-q", str(repo)], capture_output=True).returncode:
        pytest.skip("git init falhou na pasta temporária (ambiente sem permissão de escrita)")
    assert project_key(str(repo / "src" / "deep")) == "path:" + repo.resolve().as_posix().lower()
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "git@github.com:Org/Repo.git"], check=True)
    assert project_key(str(repo)) == "github.com/org/repo"


@pytest.fixture
def items(test_engine: Engine) -> ItemService:
    return ItemService(test_engine)


@pytest.fixture
def linked(test_engine, items):
    ProjectService(test_engine).link("github.com/org/app", "Polara", "app")
    return lambda dm="app", ws="Polara", **kw: items.batch_upsert(
        [{"workspace": ws, "domain": dm, **BASE, **kw}])


def _ctx(test_engine, **kw):
    return ContextService(test_engine).build("github.com/org/app", **kw)


def test_projeto_nao_ligado_explica_como_ligar(test_engine):
    out = ContextService(test_engine).build("github.com/org/outro")
    assert out["linked"] is False and "/plumb-setup" in out["markdown"]


def test_link_e_resolve(test_engine):
    ProjectService(test_engine).link("git@github.com:Org/App.git", "Polara", "app")
    found = ProjectService(test_engine).resolve("https://github.com/org/app")
    assert (found["workspace"], found["domain"]) == ("Polara", "app")


def test_link_sem_workspace_usa_o_dono_e_o_repo(test_engine):
    out = ProjectService(test_engine).link("git@github.com:Polara-Innovations/projpro.git")
    assert (out["workspace"], out["domain"]) == ("polara-innovations", "projpro")
    out = ProjectService(test_engine).link("path:c:/projects/meu-app")
    assert (out["workspace"], out["domain"]) == ("Pessoal", "meu-app")


def test_segundo_repo_do_mesmo_dono_cai_no_mesmo_workspace(test_engine):
    ProjectService(test_engine).link("github.com/polara-innovations/projpro", "Polara")
    out = ProjectService(test_engine).link("github.com/polara-innovations/synapse")
    assert (out["workspace"], out["domain"]) == ("Polara", "synapse")
    outro = ProjectService(test_engine).link("github.com/kaualealz/plumb-harness")
    assert outro["workspace"] == "kaualealz"  # outro dono: não herda


def test_repos_do_mesmo_workspace_dividem_o_geral_mas_nao_o_resto(test_engine, items):
    ProjectService(test_engine).link("github.com/org/a", "Org")
    ProjectService(test_engine).link("github.com/org/b", "Org")
    items.batch_upsert([
        {"workspace": "Org", "domain": "a", "key": "r", "type": "rule", **BASE,
         "title": "Regra do A"},
        {"workspace": "Org", "domain": "Geral", "key": "c", "type": "rule", **BASE,
         "title": "Convenção da empresa"},
        {"workspace": "Global", "domain": "Geral", "key": "g", "type": "rule", **BASE,
         "title": "Responder em PT-BR"},
    ])
    md_b = ContextService(test_engine).build("github.com/org/b")["markdown"]
    assert "Responder em PT-BR" in md_b and "Convenção da empresa" in md_b
    assert "Regra do A" not in md_b


def test_contexto_em_ordem_e_sem_inativos(test_engine, linked):
    linked(key="r1", type="rule", title="Regra oficial", memory_class="canonical")
    linked(key="r2", type="rule", title="Regra nova", memory_class="working")
    linked(key="c1", type="context", title="Stack do app")
    linked(key="old", type="rule", title="Regra velha", status="superseded")
    linked(key="tmp", type="rule", title="Nota temporária", memory_class="ephemeral", ttl_days=3)
    md = _ctx(test_engine)["markdown"]
    assert md.index("Regra oficial") < md.index("Regra nova") < md.index("Stack do app")
    assert "rascunho" not in md and "`r1`" in md  # não há mais aprovação
    assert "Regra velha" not in md and "Nota temporária" not in md
    assert "content" not in md and "corpo" not in md


def test_escopo_por_caminho(test_engine, linked):
    linked(key="pay", type="rule", title="Money em pagamentos",
           scope_paths=["src/payments/**"])
    sem = _ctx(test_engine)["markdown"]
    assert "## Regras com escopo" in sem and "Money em pagamentos — src/payments/**" in sem
    com = _ctx(test_engine, paths=["src/payments/api/Charge.java"])["markdown"]
    assert "**Money em pagamentos**" in com and "Regras com escopo" not in com
    fora = _ctx(test_engine, paths=["src/users/User.java"])["markdown"]
    assert "**Money em pagamentos**" not in fora


def test_geral_do_workspace_e_global_entram(test_engine, linked):
    linked(key="g1", type="rule", title="Convenção da Polara", dm="Geral")
    linked(key="p1", type="rule", title="Responder em PT-BR", ws="Global", dm="Geral")
    linked(key="x", type="rule", title="Regra de outro projeto", dm="outro")
    md = _ctx(test_engine)["markdown"]
    assert "Convenção da Polara" in md and "Responder em PT-BR" in md
    assert "Regra de outro projeto" not in md


def test_orcamento_corta_e_avisa(test_engine, linked):
    for i in range(60):
        linked(key=f"k{i}", type="knowledge", title=f"Aprendizado {i}", summary="x" * 120)
    out = _ctx(test_engine, budget_tokens=300)
    assert len(out["markdown"]) <= 300 * 4 + 120
    assert out["omitted"] > 0 and "fora do orçamento" in out["markdown"]


def test_query_traz_o_item_em_foco_com_content_e_sem_repetir(test_engine, linked):
    linked(key="f", type="procedure", title="Migrações com Flyway", content="Rodar migrate antes")
    md = _ctx(test_engine, query="migração")["markdown"]
    assert "## Em foco" in md and md.count("Migrações com Flyway") == 1
    assert "> Rodar migrate antes" in md


def test_foco_por_caminho_traz_content_e_fora_do_foco_nao(test_engine, linked):
    linked(key="pay", type="rule", title="Money em pagamentos", summary="Sempre em centavos",
           content="Exemplo: 1990 = R$ 19,90", scope_paths=["src/payments/**"])
    linked(key="g", type="rule", title="Geral", content="detalhe longo")
    md = _ctx(test_engine, paths=["src/payments/Charge.java"])["markdown"]
    assert "## Em foco" in md and "> Exemplo: 1990" in md
    assert "detalhe longo" not in md  # fora do foco: só título e resumo


def test_area_sensivel_pela_keyword_e_pelo_caminho(test_engine, linked):
    linked(key="pay", type="rule", title="Pagamentos", keywords="dinheiro sensível",
           scope_paths=["src/payments/**"])
    assert _ctx(test_engine, paths=["src/payments/a.js"])["sensitive"] is True
    assert "Área sensível" in _ctx(test_engine, paths=["src/payments/a.js"])["markdown"]
    assert _ctx(test_engine, paths=["src/users/a.js"])["sensitive"] is False
    assert _ctx(test_engine)["sensitive"] is False


def test_tudo_que_chega_ao_agente_conta_uso(test_engine, linked, items):
    """Uso = o item chegou a um agente (pacote, foco, busca, item_get) — base da limpeza."""
    linked(key="pay", type="rule", title="Money", scope_paths=["src/payments/**"])
    linked(key="g", type="rule", title="Geral")
    _ctx(test_engine)  # `pay` só aparece pelo título na lista de regras com escopo: não conta
    _ctx(test_engine, paths=["src/payments/a.js"])
    uses = {r["key"]: r["uses"] for r in items.search(None, None, "", limit=10, track=False)}
    assert uses == {"pay": 1, "g": 2}


def test_sugere_retro_depois_de_5_mudancas_concluidas(test_engine, linked):
    for i in range(4):
        linked(key=f"mudanca/m{i}", type="task", title=f"Mudança {i}", status="done")
    assert "plumb-retro" not in _ctx(test_engine)["markdown"]
    linked(key="mudanca/m4", type="task", title="Mudança 4", status="done")
    out = _ctx(test_engine)
    assert out["retro_due"] == 5 and "/plumb-retro" in out["markdown"]
    assert "Mudança 4" not in out["markdown"]  # concluída sai do pacote
    linked(key="retro/ultima", type="task", title="Retro", status="done")
    assert _ctx(test_engine)["retro_due"] == 0
