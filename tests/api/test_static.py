"""Front estático em /ui/: servido sem autenticação, sem build step e sem Tailwind."""

import re
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowledge_os.api.main import app

STATIC = Path(__file__).resolve().parents[2] / "src" / "knowledge_os" / "api" / "static"

ASSETS = [
    "css/tokens.css",
    "css/app.css",
    "js/main.js",
    "js/api.js",
    "js/router.js",
    "js/store.js",
    "js/util.js",
    "js/views/sidebar.js",
    "js/views/workspace.js",
    "js/views/domain.js",
    "js/views/listing.js",
    "js/markdown.js",
    "js/views/item.js",
    "js/views/palette.js",
    "js/shortcuts.js",
    "js/views/editor.js",
    "js/views/connections.js",
]


@pytest.fixture(scope="module")
def ui():
    return TestClient(app)


def test_index_servido_em_ui(ui):
    resp = ui.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Knowledge OS" in resp.text
    assert 'type="importmap"' not in resp.text  # bibliotecas locais, sem CDN


def test_health_continua_em_raiz(ui):
    assert ui.get("/").json()["status"] == "ok"


def test_api_nao_e_engolida_pelo_mount(ui):
    # A rota da API existe (não é engolida pelo mount estático): nunca 404.
    assert ui.get("/api/workspaces").status_code != 404


@pytest.mark.parametrize("path", ASSETS)
def test_assets_prometidos_sao_servidos(ui, path):
    resp = ui.get(f"/ui/{path}")
    assert resp.status_code == 200, path
    assert len(resp.text) > 20


def test_sem_tailwind_e_sem_build_step():
    for f in STATIC.rglob("*"):
        if f.is_file():
            text = f.read_text(encoding="utf-8").lower()
            assert "tailwind" not in text, f
    assert not (STATIC / "package.json").exists()


CONN_OPEN = "<!-- Configurações · Conexões"
CONN_CLOSE = "<!-- /Configurações · Conexões"


def _static_files():
    return [f for f in STATIC.rglob("*") if f.is_file()]


SECRET_OPEN = "<!-- Segredo · valor -->"
SECRET_CLOSE = "<!-- /Segredo · valor -->"


def test_campo_de_senha_so_nas_conexoes_e_no_valor_do_segredo():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert CONN_OPEN in html and CONN_CLOSE in html
    inside = html[html.index(CONN_OPEN):html.index(CONN_CLOSE)]
    secret = html[html.index(SECRET_OPEN):html.index(SECRET_CLOSE)]
    assert inside.count('type="password"') == secret.count('type="password"') == 1
    assert html.count('type="password"') == 2
    assert 'autocomplete="new-password"' in inside
    # o do segredo não oferece "salvar senha" no navegador nem fica num <form>
    assert 'autocomplete="off"' in secret and "data-1p-ignore" in secret
    assert "<form" not in secret
    for f in _static_files():
        if f.name != "index.html":
            text = f.read_text(encoding="utf-8")
            assert 'type="password"' not in text and "type=password" not in text, f.name


def test_senha_so_e_escrita_nunca_lida_de_volta():
    for f in (STATIC / "js").rglob("*.js"):
        text = f.read_text(encoding="utf-8")
        mentions = re.findall(r"(?<![\w])password(?!_set)", text)
        if f.name != "connections.js":
            assert not mentions, f.name  # fora da view, só `password_set` aparece
    conn = _js("views/connections.js")
    # `.password` só em `this.password` (campo do formulário) e `body.password` (corpo enviado)
    assert not re.findall(r"(?<!this)(?<!body)\.password(?!_)", conn)
    assert not re.findall(r"\?\.password", conn)
    # nunca em storage, console, toast ou URL
    for banned in ("localStorage", "sessionStorage", "lsSet", "lsGet", "console."):
        assert banned not in conn, banned
    for line in conn.splitlines():
        if "toast(" in line or "query" in line or "href" in line or "location" in line:
            assert "password" not in line.lower(), line
    assert not re.search(r"[?&]password=", conn)
    # enviada só no corpo e só quando preenchida; null quando "remover senha"
    assert "if (this.password)" in conn and "removePassword" in conn
    assert "this.password = ''" in conn


def test_view_de_conexoes_tem_as_acoes_pedidas():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    inside = html[html.index(CONN_OPEN):html.index(CONN_CLOSE)]
    for needle in (
        "connectionsView", "Testar", "Salvar e testar", "Definir como default",
        "Sincronizar schema", "Zona de perigo", "Default", "senha definida",
    ):
        assert needle in inside, needle
    conn = _js("views/connections.js")
    for needle in ("'PATCH'", "'POST'", "'PUT'", "'DELETE'", "schema-sync", "dry_run", "/test"):
        assert needle in conn, needle
    assert "confirmName" in conn


def test_index_referencia_apenas_arquivos_locais_existentes():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?<![:\w-])(?:src|href)="((?!https?:|#|data:)[^"]+)"', html)
    assert any(r.endswith("main.js") for r in refs)
    for ref in refs:
        assert (STATIC / ref).is_file(), ref


def test_imports_relativos_dos_modulos_existem():
    for f in (STATIC / "js").rglob("*.js"):
        for rel in re.findall(r"from\s+'(\.[^']+)'", f.read_text(encoding="utf-8")):
            assert (f.parent / rel).resolve().is_file(), f"{f.name} -> {rel}"


def test_front_nao_tem_token_nem_login():
    for f in (STATIC / "js").rglob("*.js"):  # o nosso código; vendor/ são bibliotecas de terceiros
        txt = f.read_text(encoding="utf-8")
        assert "Authorization" not in txt and "sessionStorage" not in txt, f.name
        assert "#token" not in txt and "captureToken" not in txt, f.name


def _js(name: str) -> str:
    return (STATIC / "js" / name).read_text(encoding="utf-8")


def test_markdown_passa_pelo_dompurify_e_nunca_por_x_html():
    md = _js("markdown.js")
    assert "DOMPurify.sanitize" in md and "marked" in md and "hljs" in md
    assert "FORBID_TAGS" in md and "FORBID_ATTR" in md
    assert "x-html" not in (STATIC / "index.html").read_text(encoding="utf-8")
    for f in (STATIC / "js").rglob("*.js"):
        assert ".innerHTML" not in f.read_text(encoding="utf-8"), f.name


def test_pagina_de_item_tem_toc_relacoes_e_banner():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'x-data="itemView"' in html
    needles = (
        "Nesta página", "Copiar como Markdown", "Ver Markdown", "Referencia", "Referenciado por",
    )
    for needle in needles:
        assert needle in html, needle
    assert "IntersectionObserver" in _js("views/item.js")


def test_paleta_e_atalhos():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'x-data="palette"' in html and 'role="dialog"' in html
    pal = _js("views/palette.js")
    for grupo in ("Recentes", "Items", "Domains e Workspaces", "Ações", "Configurações"):
        assert f"'{grupo}'" in pal, grupo
    assert "/items/search" in pal
    sc = _js("shortcuts.js")
    for needle in ("Escape", "metaKey", "'?'", "registerShortcuts"):
        assert needle in sc, needle
    assert "registerShortcuts" in _js("main.js")


def test_edicao_inline_e_modais_de_criacao():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for needle in ("itemEditor", "newModal", "Novo item", "Novo workspace", "Novo domain"):
        assert needle in html, needle
    ed = _js("views/editor.js")
    assert "beforeunload" in ed and "'PUT'" in ed and "'POST'" in ed
    assert "/workspaces" in ed and "/domains" in ed and "/items" in ed
    sc = _js("shortcuts.js")
    assert "saveHook" in sc and "toggleEdit" in sc
    assert "Ctrl S" in sc or "⌘ S" in sc


def test_responsivo_e_estados():
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert "max-width: 768px" in css and "max-width: 1000px" in css
    assert "drawer-open" in css and "prefers-reduced-motion" in css
    assert "overflow-x: hidden" in css or "overflow-x: clip" in css
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Sessão expirada" not in html
    # a falha de listagem aparece também na página de Workspace, não só na lista da conexão
    assert html.count("$store.app.wsError") >= 3
    assert "Tentar de novo" in html and 'role="alert"' in html


def test_editor_so_renderiza_com_o_item_da_rota():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "route.params.edit && item && item.id === $store.app.route.params.item" in html
    assert "this.item.id !== id) this.item = null" in _js("views/item.js")


def test_erro_de_conexoes_nao_fabrica_default():
    st = _js("store.js")
    assert "connError" in st
    assert "list = [];" not in st
    assert "this.connError = e.message" in st
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count("$store.app.connError") >= 3


def test_load_workspaces_descarta_resposta_antiga():
    st = _js("store.js")
    assert "++this.wsSeq" in st and st.count("seq !== this.wsSeq") >= 2


def test_pagina_de_domain_usa_limite_maximo_e_avisa():
    lst = _js("views/listing.js")
    assert "LIMIT = 500" in lst and "limit: LIMIT" in lst
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Mostrando " in html and "truncated" in html


def test_nenhum_arquivo_estatico_menciona_401():
    for f in _static_files():
        assert "401" not in f.read_text(encoding="utf-8"), f.name


def test_fechar_modal_sujo_pede_confirmacao():
    assert "app.closeModal()" in _js("shortcuts.js")
    assert "Descartar o que foi digitado?" in _js("store.js")
    assert "modalGuard" in _js("views/editor.js")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count("close()") >= 3



def test_mapa_de_tipos_cobre_todos_os_tipos_da_api():
    from knowledge_os.schemas.item_schemas import ITEM_TYPES

    util = _js("util.js")
    meta = util[util.index("export const TYPE_META"):util.index("export const TYPE_ORDER")]
    for t in (*ITEM_TYPES, "secret"):
        assert re.search(rf"\b{t}: {{ label: '[^']+', plural: '[^']+' }}", meta), t
    labels = dict(re.findall(r"(\w+): \{ label: '([^']+)'", meta))
    assert labels["rule"] == "Regra" and labels["insight"] == "Decisão"
    assert labels["task"] == "Mudança" and labels["knowledge"] == "Aprendizado"
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    for t in (*ITEM_TYPES, "secret"):
        assert tokens.count(f"--t-{t}:") == 3, t  # claro, escuro (media) e escuro (data-theme)


def test_ui_sem_vestigios_de_aprovacao():
    banned = re.compile(
        r"memory_class|memoryClass|MEMORY_CLASSES|confidence|importance|\bttl|ttl_days|\$conf|mc-",
        re.I,
    )
    files = [STATIC / "index.html", *(STATIC / "js").rglob("*.js"), STATIC / "css" / "app.css"]
    for f in files:
        if "vendor" in f.parts:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if banned.search(line):
                # único uso permitido: a UI cria itens sempre como longterm.
                assert f.name == "editor.js" and "memory_class: 'longterm'" in line, (f.name, line)


def test_tema_so_claro_e_escuro_com_dica_em_portugues():
    st = _js("store.js")
    assert "THEMES" not in st and "cycleTheme" not in st
    assert "Mudar para tema claro" in st and "Mudar para tema escuro" in st
    assert "prefers-color-scheme" in st
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "toggleTheme()" in html and "'sun' : 'moon'" in html


def test_largura_larga_sem_teto_e_botao_oculto_quando_nao_cabe():
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert "1040px" not in css
    assert ".app.wide .page { grid-template-columns: minmax(0, 1fr); }" in css
    assert re.search(r"@media \(max-width: \d+px\) \{ \.btn\.wide-btn \{ display: none; \} \}", css)


def test_listas_agrupadas_por_tipo_com_filtros_e_busca():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count('class="filterbar"') == 2 and "Todos os itens" in html
    lst = _js("views/listing.js")
    assert "groupByType" in lst and "/items/search" in lst and "types" in lst
    util = _js("util.js")
    block = re.search(r"export const TYPE_META = \{(.*?)\n\};", util, re.S).group(1)
    keys = re.findall(r"^  (\w+): \{", block, re.M)
    assert keys[:8] == [
        "rule", "insight", "procedure", "pattern", "knowledge", "context", "task", "artifact",
    ]


def test_paleta_busca_em_todos_os_workspaces_com_ate_20_resultados():
    pal = _js("views/palette.js")
    assert "REMOTE_LIMIT = 20" in pal and "workspace_id: ws" not in pal
    assert "r.workspace_id" in pal and "r.domain_id" in pal



# ---- identidade visual: logo única, sprite coerente, tipos sem ícone ----
def _index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _js_sources() -> str:
    files = (STATIC / "js").rglob("*.js")
    return "\n".join(p.read_text(encoding="utf-8") for p in files if "vendor" not in p.parts)


def _norm(svg: str) -> str:
    return re.sub(r"\s+", "", svg.replace('"', "'"))


def test_favicon_e_cabecalho_usam_a_mesma_logo():
    html = _index()
    href = re.search(r'<link rel="icon" href="data:image/svg\+xml,([^"]+)"', html).group(1)
    favicon = urllib.parse.unquote(href)
    inner_fav = re.search(r"<svg[^>]*>(.*)</svg>", favicon, re.S).group(1)
    inner_sprite = re.search(r'<symbol id="logo"[^>]*>(.*?)</symbol>', html, re.S).group(1)
    assert _norm(inner_fav) == _norm(inner_sprite)
    assert html.count('<symbol id="logo"') == 1
    brand = re.search(r'<a class="brand".*?</a>', html, re.S).group(0)
    assert 'href="#logo"' in brand
    assert "Knowledge OS" in brand


def test_sprite_sem_orfaos_e_sem_referencias_quebradas():
    html = _index()
    ids = set(re.findall(r'<symbol id="([^"]+)"', html))
    body = html.split("</svg>", 1)[1]  # fora do sprite
    refs = set(re.findall(r"#(i-[a-z-]+|logo)\b", body))
    # nomes escolhidos em tempo de execução: `'#i-' + (cond ? 'a' : 'b')` (HTML) e `icon: 'a'` (JS)
    dyn = re.findall(r"'#i-' \+ \([^?]*\? '([a-z-]+)' : '([a-z-]+)'\)", body)
    refs |= {"i-" + n for pair in dyn for n in pair}
    for m in re.finditer(r"\bicon: (?:[^'\n,]*\? )?'([a-z-]+)'(?: : '([a-z-]+)')?", _js_sources()):
        refs |= {"i-" + n for n in m.groups() if n}
    assert not (refs - ids), f"referências quebradas: {sorted(refs - ids)}"
    assert not (ids - refs), f"símbolos órfãos: {sorted(ids - refs)}"
    assert not re.search(r"<svg[^>]*style=", body)  # tamanhos e cores por classe CSS


def test_linhas_de_item_nao_usam_icone_de_tipo():
    html = _index()
    assert "$icon(" not in html
    rows = re.findall(r'<a class="item-row".*?</a>', html, re.S)
    assert rows
    for row in rows:
        assert "<svg" not in row
        assert row.count('class="tbadge"') == 1
    assert "icon:" not in (STATIC / "js" / "util.js").read_text(encoding="utf-8")
