"""Tela de conexões: só lista, edita, define a padrão e apaga — criar é pelo MCP.

Sem nenhuma conexão, a tela inicial e a de conexões explicam como criar uma com
`connection_create` (nada de tela branca).
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "knowledge_os" / "api" / "static"
CONN_OPEN = "<!-- Configurações · Conexões"
CONN_CLOSE = "<!-- /Configurações · Conexões"
HOME_OPEN = "<!-- Início sem conexão -->"
HOME_CLOSE = "<!-- /Início sem conexão -->"
EXEMPLO = 'connection_create(name="pessoal", path="C:\\\\caminho\\\\da\\\\pasta")'


def _html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _js(rel: str) -> str:
    return (STATIC / "js" / rel).read_text(encoding="utf-8")


def _conn_section() -> str:
    html = _html()
    return html[html.index(CONN_OPEN) : html.index(CONN_CLOSE)]


def test_ui_nao_cria_conexao():
    html = _html()
    section = _conn_section()
    view = _js("views/connections.js")
    for needle in ("connections/new", "New connection", "Nova conexão", "isNew"):
        assert needle not in html, needle
        assert needle not in view, needle
    # sem POST de criação nem o seletor de pasta que só servia a ela
    assert "'POST', '/connections'" not in view
    assert "/fs/browse" not in view and "openBrowse" not in view
    assert "browse." not in section and 'id="c-path"' not in section
    # o único POST que sobra é o de testar
    assert view.count("'POST'") == 1 and "/test`" in view
    assert "/new" not in _js("router.js")


def test_lista_mostra_caminho_remote_modo_padrao_e_estado():
    section = _conn_section()
    for needle in ("c.path", "c.remote_url", "c.review_mode", "c.is_default", "folderState(c)"):
        assert needle in section, needle
    view = _js("views/connections.js")
    assert "path_exists" in view and "is_git_repo" in view
    store = _js("store.js")
    for campo in ("path:", "path_exists:", "is_git_repo:"):
        assert campo in store.split("function normalizeConnection")[1].split("}")[0], campo


def test_edicao_mantem_nome_remote_modo_e_ativar():
    section = _conn_section()
    for model in ('x-model="form.name"', 'x-model="form.remote_url"',
                  'x-model="form.review_mode"', 'x-model="form.enabled"'):
        assert model in section, model
    view = _js("views/connections.js")
    for needle in ("'PATCH'", "'PUT'", "'DELETE'", "/default", "confirmName"):
        assert needle in view, needle


def test_estado_vazio_ensina_connection_create():
    html = _html()
    section = _conn_section()
    assert HOME_OPEN in html and HOME_CLOSE in html
    home = html[html.index(HOME_OPEN) : html.index(HOME_CLOSE)]
    assert "route.name === 'home'" in home and "!$store.app.connections.length" in home
    for bloco in (home, section):
        assert "Nenhuma conexão" in bloco
        assert "pelo MCP" in bloco
        assert EXEMPLO in bloco
    assert "!$store.app.connections.length" in section
