"""Pacote de contexto do hook (V2_MVP.md §10): a mesma cadeia de alcance da busca, as seções
em ordem, a origem marcada nos itens de fora do project, o orçamento e o texto de como resolver
quando não há ligação ou conexão."""

import pytest

from knowledge_os.config import NO_CONNECTION_MESSAGE
from knowledge_os.services.brain import Brain
from knowledge_os.services.context_service import ContextService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.repo_service import RepoService
from knowledge_os.services.secret_service import SecretService

REPO = "github.com/org/app"
SECTIONS = ["## Em foco", "## ⚠ Em revisão", "## Segurança", "## Regras", "## Contexto",
            "## Como fazer", "## Specs ativas", "## Segredos", "## Regras com escopo"]


@pytest.fixture
def save(conn):
    RepoService().link(REPO, "W", "P")

    def _save(key, type_="rule", ws="W", pj="P", **extra):
        entry = {"workspace": ws, "project": pj, "key": key, "type": type_,
                 "title": extra.pop("title", key), "summary": extra.pop("summary", "resumo"),
                 "content": extra.pop("content", "corpo do item"), **extra}
        if type_ == "secret":
            entry.pop("content")
        return ItemService().save([entry])[0]["id"]

    return _save


def _pack(**kw):
    return ContextService().build(REPO, **kw)


def _section(md, title):
    """Texto da seção `title` (até o próximo `## `)."""
    start = md.index(title)
    nxt = md.find("\n## ", start + len(title))
    return md[start:nxt if nxt != -1 else len(md)]


def test_secoes_em_ordem(save):
    save("rule/sem-log", subtype="security", title="Segredo nunca no log")
    save("rule/money", subtype="code", title="Use Money")
    save("rule/revisar", subtype="code", title="Regra duvidosa", status="review")
    save("context/stack", title="Stack Java 21", type_="context")
    save("howto/deploy", type_="howto", title="Deploy no Railway", content="passo secreto")
    save("spec/migrar", type_="spec", title="Migrar pagamentos", summary="fase 2 de 3")
    save("secret/npm", type_="secret", title="Token do npm", summary="publicar pacotes")
    save("rule/pay", subtype="business", title="Centavos em pagamentos",
         scope_paths=["src/payments/**"])
    out = _pack(paths=["src/payments/a.py"])
    md = out["markdown"]
    assert out["linked"] is True and (out["workspace"], out["project"]) == ("W", "P")
    positions = [md.index(title) for title in SECTIONS]
    assert positions == sorted(positions), md
    assert "[code]" in _section(md, "## Regras\n") and "Use Money" in _section(md, "## Regras\n")
    assert "Segredo nunca no log" in _section(md, "## Segurança")
    assert "Regra duvidosa" in _section(md, "## ⚠ Em revisão")
    assert "Deploy no Railway" in _section(md, "## Como fazer")
    assert "passo secreto" not in md  # Como fazer: só títulos
    assert "fase 2 de 3" in _section(md, "## Specs ativas")
    assert "Centavos em pagamentos" in _section(md, "## Em foco")
    assert "Centavos em pagamentos" in _section(md, "## Regras com escopo")
    assert out["included"] >= 8 and out["omitted"] == 0


def test_spec_done_e_arquivados_nao_aparecem(save):
    save("spec/feita", type_="spec", title="Spec concluida", status="done")
    save("spec/rascunho", type_="spec", title="Spec em rascunho", status="draft")
    save("rule/velha", title="Regra arquivada", status="archived")
    md = _pack()["markdown"]
    assert "Spec concluida" not in md and "Regra arquivada" not in md
    assert "Spec em rascunho" in _section(md, "## Specs ativas")


def test_alcance_e_origem_marcada(save):
    save("rule/local", title="Regra do proprio project")
    save("rule/global", ws="E", pj="Q", scope="global", title="Responder em PT-BR")
    save("rule/do-ws", pj="Geral", scope="workspace", title="Convencao do workspace")
    save("rule/outro", pj="Outro", title="Regra de outro project")
    save("rule/fora", ws="E", pj="Q", title="Scoped de outro workspace")
    md = _pack()["markdown"]
    lines = {ln for ln in md.splitlines() if ln.startswith("- ")}
    line = next(ln for ln in lines if "Responder em PT-BR" in ln)
    assert "[global]" in line
    line = next(ln for ln in lines if "Convencao do workspace" in ln)
    assert "[W]" in line
    line = next(ln for ln in lines if "Regra do proprio project" in ln)
    assert "[global]" not in line and "[W]" not in line
    assert "Regra de outro project" not in md and "Scoped de outro workspace" not in md


def test_em_foco_por_query_traz_trecho_do_content(save):
    save("howto/flyway", type_="howto", title="Migrações com Flyway",
         content="Rodar migrate antes do deploy")
    md = _pack(query="flyway")["markdown"]
    foco = _section(md, "## Em foco")
    assert "Migrações com Flyway" in foco and "Rodar migrate antes" in foco
    assert md.count("Migrações com Flyway") == 1


def test_em_foco_por_paths_e_sensivel_so_por_rule_security(save):
    save("rule/pay", subtype="security", title="PCI em pagamentos",
         content="Nunca logar o cartao", scope_paths=["src/payments/**"])
    save("rule/kw", subtype="code", title="Palavra antiga", keywords="sensivel",
         scope_paths=["src/users/**"])
    com = _pack(paths=["src/payments/api/Charge.java"])
    assert com["sensitive"] is True and "Área sensível" in com["markdown"]
    assert "Nunca logar o cartao" in _section(com["markdown"], "## Em foco")
    fora = _pack(paths=["src/users/User.java"])
    assert fora["sensitive"] is False  # `sensivel` em keywords não tem mais efeito
    assert "PCI em pagamentos" not in fora["markdown"]
    assert _pack()["sensitive"] is False


def test_regras_com_escopo_sem_paths_viram_lembrete(save):
    save("rule/pay", subtype="code", title="Money em pagamentos",
         content="detalhe longo", scope_paths=["src/payments/**"])
    md = _pack()["markdown"]
    escopo = _section(md, "## Regras com escopo")
    assert "Money em pagamentos" in escopo and "src/payments/**" in escopo
    assert "detalhe longo" not in md and "## Em foco" not in md


def test_segredo_mostra_estado_e_como_usar(save):
    vazio = save("secret/npm", type_="secret", title="Token do npm", summary="publicar")
    cheio = save("secret/gh", type_="secret", title="Token do GitHub", summary="gh api")
    SecretService().set_value(cheio, "ghp_valor-de-teste-bem-comprido-123")
    segredos = _section(_pack()["markdown"], "## Segredos")
    npm = next(ln for ln in segredos.splitlines() if "Token do npm" in ln)
    assert "sem valor" in npm and f"/i/{vazio}" in npm
    gh = next(ln for ln in segredos.splitlines() if "Token do GitHub" in ln)
    assert "knowledge-mcp run --env VAR=secret/gh -- <comando>" in gh
    assert "ghp_valor" not in segredos


def test_orcamento_corta_e_lista_o_omitido(save):
    ItemService().save([
        {"workspace": "W", "project": "P", "key": f"rule/k{i:02d}", "type": "rule",
         "title": f"Regra {i}", "summary": "x" * 120, "content": "c"}
        for i in range(20)
    ])
    out = _pack(budget_tokens=200)
    md = out["markdown"]
    assert out["omitted"] > 0 and "fora do orçamento" in md
    assert len(md) <= 200 * 4 + 400
    omitted = [k for k in out["omitted_keys"]]
    assert omitted and omitted[0] in md


def test_itens_do_pacote_somam_shown(save):
    item_id = save("rule/money", subtype="code", title="Use Money")
    _pack()
    assert Brain().usage()[item_id]["shown"] == 1


def test_projeto_nao_ligado_diz_como_ligar(conn):
    out = ContextService().build("github.com/org/outro")
    assert out["linked"] is False
    assert 'repo(action="link"' in out["markdown"] and "/plumb-setup" in out["markdown"]


def test_sem_conexao_diz_como_criar():
    out = ContextService().build(REPO)
    assert out["linked"] is False and NO_CONNECTION_MESSAGE in out["markdown"]
