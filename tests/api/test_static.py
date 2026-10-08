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
    "js/views/project.js",
    "js/views/listing.js",
    "js/markdown.js",
    "js/views/item.js",
    "js/views/graph.js",
    "js/views/palette.js",
    "js/shortcuts.js",
    "js/views/editor.js",
    "js/views/connections.js",
    "js/views/subject.js",
    "js/views/tags.js",
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


CONN_OPEN = "<!-- Settings · Connections"
CONN_CLOSE = "<!-- /Settings · Connections"


def _static_files():
    return [f for f in STATIC.rglob("*") if f.is_file()]


SECRET_OPEN = "<!-- Segredo · valor -->"
SECRET_CLOSE = "<!-- /Segredo · valor -->"


def test_campo_de_senha_so_no_valor_do_segredo():
    # Conexões não têm senha (são pastas/repositórios git): o único campo de senha
    # que resta na UI é o valor do segredo.
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert CONN_OPEN in html and CONN_CLOSE in html
    inside = html[html.index(CONN_OPEN) : html.index(CONN_CLOSE)]
    secret = html[html.index(SECRET_OPEN) : html.index(SECRET_CLOSE)]
    assert inside.count('type="password"') == 0
    assert secret.count('type="password"') == 1
    assert html.count('type="password"') == 1
    # o do segredo não oferece "salvar senha" no navegador nem fica num <form>
    assert 'autocomplete="off"' in secret and "data-1p-ignore" in secret
    assert "<form" not in secret
    for f in _static_files():
        if f.name != "index.html":
            text = f.read_text(encoding="utf-8")
            assert 'type="password"' not in text and "type=password" not in text, f.name


def test_senha_so_e_escrita_nunca_lida_de_volta():
    # Nenhum arquivo JS (inclusive a view de conexões, que não lida mais com senha) fala
    # de `password` fora de `password_set` — isso é assunto só do segredo (secret_service).
    for f in (STATIC / "js").rglob("*.js"):
        text = f.read_text(encoding="utf-8")
        mentions = re.findall(r"(?<![\w])password(?!_set)", text)
        assert not mentions, f.name


def test_view_de_conexoes_tem_as_acoes_pedidas():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    inside = html[html.index(CONN_OPEN) : html.index(CONN_CLOSE)]
    for needle in (
        "connectionsView",
        "'Test'",
        "Save and test",
        "Make default",
        "Danger zone",
        "$connbadges(",
    ):
        assert needle in inside, needle
    conn = _js("views/connections.js")
    for needle in ("'PATCH'", "'POST'", "'PUT'", "'DELETE'", "/test"):
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
        "On this page",
        "Copy as Markdown",
        "View Markdown",
        "References",
        "Referenced by",
    )
    for needle in needles:
        assert needle in html, needle
    assert "IntersectionObserver" in _js("views/item.js")


def test_pagina_de_item_tem_acao_de_excluir():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '@click="remove()"' in html
    it = _js("views/item.js")
    assert "async remove()" in it
    assert "DELETE', `/items/" in it
    # arma com um clique, apaga só no segundo (mesmo padrão do clear() de secretForm)
    assert "confirmingDelete" in it
    # se o usuário já navegou pra outro item antes do DELETE resolver, não arrasta ele de
    # volta pro project do item antigo (achado por um revisor independente)
    assert "const mine = this.seq" in it
    assert "mine !== this.seq" in it


def test_paleta_e_atalhos():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'x-data="palette"' in html and 'role="dialog"' in html
    pal = _js("views/palette.js")
    for grupo in ("Recent", "Items", "Projects & workspaces", "Actions", "Settings"):
        assert f"'{grupo}'" in pal, grupo
    assert "/items/search" in pal
    sc = _js("shortcuts.js")
    for needle in ("Escape", "metaKey", "'?'", "registerShortcuts"):
        assert needle in sc, needle
    assert "registerShortcuts" in _js("main.js")


def test_edicao_inline_e_modais_de_criacao():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for needle in ("itemEditor", "newModal", "New item", "New workspace", "New project"):
        assert needle in html, needle
    ed = _js("views/editor.js")
    assert "beforeunload" in ed and "'PUT'" in ed and "'POST'" in ed
    assert "/workspaces" in ed and "/projects" in ed and "/items" in ed
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
    assert "Try again" in html and 'role="alert"' in html


def test_botoes_de_acao_ficam_ao_lado_do_titulo_nao_abaixo():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert css.count(".page-head") >= 3
    # Workspaces, Workspace, Project e Conexões: título + toolbar na mesma div.page-head
    assert html.count('<div class="page-head">') >= 4


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


def test_listagem_pagina_com_anterior_proxima_em_vez_de_carregar_tudo():
    lst = _js("views/listing.js")
    assert "pageSize" in lst and "totalPages" in lst and "goToPage" in lst
    assert "nextPage" in lst and "prevPage" in lst
    assert "limit: this.pageSize" in lst
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count('@click="prevPage()"') == 3
    assert html.count('@click="nextPage()"') == 3
    assert "totalPages" in html


def test_nenhum_arquivo_estatico_menciona_401():
    for f in _static_files():
        assert "401" not in f.read_text(encoding="utf-8"), f.name


def test_fechar_modal_sujo_pede_confirmacao():
    assert "app.closeModal()" in _js("shortcuts.js")
    assert "Discard what you typed?" in _js("store.js")
    assert "modalGuard" in _js("views/editor.js")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count("close()") >= 3


def test_mapa_de_tipos_cobre_os_tipos_e_subtipos_do_model():
    from knowledge_os.model import TYPES

    util = _js("util.js")
    meta = util[util.index("export const TYPE_META") : util.index("export const TYPE_ORDER")]
    for t, subtypes in TYPES.items():
        m = re.search(rf"\b{t}: {{ label: '[^']+', subtypes: \[([^\]]*)\] }}", meta)
        assert m, t
        assert re.findall(r"'(\w+)'", m.group(1)) == list(subtypes), t
    labels = dict(re.findall(r"(\w+): \{ label: '([^']+)'", meta))
    assert set(labels) == set(TYPES)
    assert labels["rule"] == "Rule" and labels["howto"] == "How-to"
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    for t in TYPES:
        assert tokens.count(f"--t-{t}:") == 3, t  # claro, escuro (media) e escuro (data-theme)
    for old in ("insight", "procedure", "pattern", "knowledge"):
        assert f"--t-{old}:" not in tokens, old


def test_ui_sem_vestigios_de_aprovacao():
    banned = re.compile(r"memory_class|memoryClass|MEMORY_CLASSES|confidence|importance|\$conf|mc-",
                        re.I)
    files = [STATIC / "index.html", *(STATIC / "js").rglob("*.js"), STATIC / "css" / "app.css"]
    for f in files:
        if "vendor" in f.parts:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            assert not banned.search(line), (f.name, line)


def test_tema_so_claro_e_escuro_com_dica_em_ingles():
    st = _js("store.js")
    assert "THEMES" not in st and "cycleTheme" not in st
    assert "Switch to light theme" in st and "Switch to dark theme" in st
    assert "prefers-color-scheme" in st
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "toggleTheme()" in html and "'sun' : 'moon'" in html


def test_largura_sempre_total_sem_botao_de_alternar():
    """O modo largo (conteúdo sem teto de largura) virou o único comportamento — não tem
    mais botão pra alternar nem estado salvo."""
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert "1040px" not in css
    assert "content-w" not in css
    assert ".page {" in css and "grid-template-columns: minmax(0, 1fr)" in css
    assert ".app.wide" not in css and ".btn.wide-btn" not in css
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "wide-btn" not in html and "toggleWide" not in html
    store = _js("store.js")
    assert "toggleWide" not in store and "kos.wide" not in store


def test_listas_sao_planas_com_filtros_e_busca():
    """A listagem é um único x-for sobre `visible` (sem agrupamento por tipo, sem título de
    seção) — type filtra client-side; project/subject vão pro servidor (ver
    test_project_e_assunto_sao_filtro...)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count('class="searchbar"') == 3 and "Todos os itens" not in html
    assert html.count('class="item-list"') == 3
    lst = _js("views/listing.js")
    assert "groupByType" not in lst
    assert "get visible()" in lst and "/items/search" in lst and "types" in lst
    util = _js("util.js")
    block = re.search(r"export const TYPE_META = \{(.*?)\n\};", util, re.S).group(1)
    keys = re.findall(r"^  (\w+): \{", block, re.M)
    assert keys == ["rule", "howto", "context", "spec", "secret"]
    assert "task" not in keys


def test_busca_tem_botao_de_filtro_com_popover_a_direita():
    """Busca e botão de filtro na mesma linha (.searchbar); o filtro abre um popover (não uma
    barra separada embaixo) — fecha ao clicar fora ou Esc."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count('class="filter-pop"') == 3
    assert html.count('class="filter-popover"') == 3
    assert html.count('@click.outside="open = false"') == 3
    assert html.count('@keydown.escape.window="open = false"') == 3
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert ".filter-popover {" in css and "position: absolute; right: 0;" in css


def test_project_e_assunto_sao_filtro_multiselect_no_servidor_nao_na_pagina_carregada():
    """type filtra só a página já carregada (client-side); project/assunto tinham que
    filtrar o total do workspace/project, não só os 50 itens da página — por isso vão de
    verdade pro servidor (query string, igual ao type na busca), não um filtro local."""
    lst = _js("views/listing.js")
    assert "toggleProjectFilter(id)" in lst and "toggleSubjectFilter(id)" in lst
    assert "query.project_id = this.filters.projectIds.join(',')" in lst
    assert "query.subject_id = this.filters.subjectIds.join(',')" in lst
    assert "q.project_id = this.filters.projectIds.join(',')" in lst
    assert "q.subject_id = this.filters.subjectIds.join(',')" in lst
    # muda projectIds/subjectIds -> recarrega a página 1 com o filtro novo
    assert "if (!this.searchMode) this.goToPage(1);" in lst
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count("toggleProjectFilter(p.id)") == 1  # só faz sentido no workspace
    assert html.count("toggleSubjectFilter(s.id)") == 2  # workspace e project


def test_filtro_de_project_so_no_workspace_assunto_nao_na_propria_pagina_do_assunto():
    """Project: filtrar por project dentro da própria página do project seria redundante
    (já é um só). Assunto: filtrar por assunto na própria página do assunto também (já é um
    assunto só) — só aparece em Workspace (todos) e Project (os do project)."""
    lst = _js("views/listing.js")
    assert "if (this.scope().project_id) return [];" in lst
    assert "if (this.scope().subject_id) return [];" in lst


def test_contador_de_itens_so_na_paginacao_nao_duplicado_embaixo_do_titulo():
    """O total já aparece na paginação (ver test_listagem_pagina_...) — repetir embaixo do
    título era redundante e um dos dois podia ficar desatualizado."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'x-text="$store.app.project.item_count"' not in html
    assert 'x-text="$store.app.subject.item_count"' not in html
    assert '<b x-text="totalItems">' not in html
    ws_block = html[html.index("<!-- Workspace -->") : html.index("<!-- Project -->")]
    assert "page-meta" not in ws_block  # contagem de projects/itens embaixo do título saiu


def test_telas_tem_botao_de_voltar():
    """Item, Project, Subject e Grafo sobem um nível (Item -> assunto/project; Project/
    Subject -> pai; Grafo -> a página do escopo que ele mostra) — Workspace não (já
    alcançável pela sidebar e pelo breadcrumb, um botão ali seria redundante)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count('class="crumb-back" :href="backHref()"') == 4
    item = _js("views/item.js")
    assert "backHref()" in item
    assert "this.item.subject_id" in item
    project = _js("views/project.js")
    assert "backHref()" in project and "hrefs.ws(" in project
    subject = _js("views/subject.js")
    assert "backHref()" in subject and "hrefs.project(" in subject
    graph = _js("views/graph.js")
    assert "backHref()" in graph
    assert "hrefs.subject(" in graph and "hrefs.project(" in graph and "hrefs.ws(" in graph


def test_workspace_sem_secao_de_projects_na_listagem():
    """Foco da página de workspace é filtrar/buscar itens — navegar pra um project
    específico é o filtro multiselect de project (acima), não uma seção de cards clicáveis
    misturada com a listagem."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    ws_block = html[html.index("<!-- Workspace -->") : html.index("<!-- Project -->")]
    assert "card-grid" not in ws_block
    assert "previewItems" not in ws_block


def test_paleta_busca_em_todos_os_workspaces_com_ate_20_resultados():
    pal = _js("views/palette.js")
    assert "REMOTE_LIMIT = 20" in pal and "workspace_id: ws" not in pal
    assert "r.workspace_id" in pal and "r.project_id" in pal


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


def test_rota_de_grafo_existe_no_router():
    router = _js("router.js")
    assert "graph: (c, w) =>" in router
    assert "seg[4] === 'graph'" in router and "name: 'graph'" in router


def test_rotas_de_subject_e_grafo_por_escopo_existem_no_router():
    router = _js("router.js")
    assert "name: 'subject'" in router
    assert "name: 'project-graph'" in router
    assert "name: 'subject-graph'" in router
    assert "subject: (c, w, p, s) =>" in router
    assert "projectGraph: (c, w, p) =>" in router
    assert "subjectGraph: (c, w, p, s) =>" in router


def test_tela_de_grafo_registrada_e_acessivel_pelo_workspace():
    html = _index()
    assert 'x-data="graphView"' in html
    assert "'graph', 'project-graph', 'subject-graph'" in html
    assert "graphHref()" in html
    main = _js("main.js")
    assert "registerGraph" in main and "views/graph.js" in main
    ws = _js("views/workspace.js")
    assert "graphHref()" in ws and "hrefs.graph" in ws


def test_grafo_tambem_acessivel_por_project_e_subject():
    html = _index()
    assert html.count("View graph</a>") >= 3  # workspace, project, subject
    project = _js("views/project.js")
    assert "graphHref()" in project and "hrefs.projectGraph" in project
    subject = _js("views/subject.js")
    assert "graphHref()" in subject and "hrefs.subjectGraph" in subject


def test_pagina_de_subject_lista_itens_filtrados_pelo_escopo():
    html = _index()
    assert 'x-data="subjectView"' in html
    assert "route.name === 'subject'" in html
    assert "$store.app.subject" in html
    main = _js("main.js")
    assert "registerSubject" in main and "views/subject.js" in main
    subject = _js("views/subject.js")
    assert "subject_id: p.subj" in subject


def test_sidebar_usa_workspace_explicito_nos_links_nao_o_da_rota_atual():
    """A sidebar mostra gavetas de workspaces que não são o da rota atual — um link de
    project/subject/item ali dentro não pode depender de route.params.ws/pj (seria o
    workspace ERRADO sempre que a gaveta aberta não é a da página atual)."""
    html = _index()
    tree = html[html.index('aria-label="Workspaces"') : html.index("side-foot")]
    assert "hProjectIn(w.id, p.id)" in tree
    assert "hSubjectIn(w.id, p.id, s.id)" in tree
    assert tree.count("hItemIn(w.id, p.id, it.id)") == 2
    store = _js("store.js")
    assert "hProjectIn(wsId, pjId)" in store
    assert "hSubjectIn(wsId, pjId, subjId)" in store
    assert "hItemIn(wsId, pjId, itemId)" in store


def test_pagina_de_workspace_sem_secao_de_atualizados_recentemente():
    """Removida — a listagem geral já ordena por mais atualizado por padrão (sort =
    'recent'), repetir num bloco separado em cima virou redundante."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Atualizados recentemente" not in html
    ws = _js("views/workspace.js")
    assert "indexed" not in ws and "get recent()" not in ws
    lst = _js("views/listing.js")
    assert "sort: 'recent'" in lst


def test_grafo_usa_d3_force_zoom_drag_e_destaca_supersedes():
    graph = _js("views/graph.js")
    for needle in (
        "d3-force.esm.js",
        "d3-zoom.esm.js",
        "d3-drag.esm.js",
        "d3-selection.esm.js",
        "forceSimulation",
        "forceManyBody",
        "forceLink",
        "forceCollide",
        "goTo(n)",
    ):
        assert needle in graph, needle
    for d3lib in ("d3-force", "d3-zoom", "d3-drag", "d3-selection"):
        vendor_path = STATIC / "vendor" / f"{d3lib}.esm.js"
        assert vendor_path.is_file(), vendor_path
        vendor_src = vendor_path.read_text(encoding="utf-8")
        assert "export{" in vendor_src or "export {" in vendor_src
    html = _index()
    inside = html[html.index("<!-- Grafo") : html.index("<!-- Project -->")]
    assert "supersedes" in inside  # destaque visual distinto no CSS escopado


def test_grafo_e_interativo_pan_zoom_arrastar():
    graph = _js("views/graph.js")
    assert ".call(zoomBehavior)" in graph  # roda do mouse / arrastar fundo = zoom/pan
    assert "drag()" in graph  # arrastar um nó
    assert "scaleExtent" in graph
    assert "alphaTarget" in graph  # solta a simulação durante o drag, acalma no fim


def test_recarga_de_listagem_nao_depende_de_qual_gaveta_carregou_por_ultimo():
    """`treeWs` era só "o último workspace cujo loadTree terminou" — com várias gavetas
    carregando em paralelo (refresh() recarrega todas as abertas de uma vez), o último a
    terminar podia não ser o da rota atual, e o $watch (que comparava contra treeWs) parava
    de disparar loadItems() pra página certa. treeVersion incrementa a cada loadTree,
    não importa qual workspace — serve de gatilho independente de ordem."""
    store = _js("store.js")
    assert "treeVersion++" in store
    for view in ("workspace.js", "project.js", "subject.js"):
        src = _js(f"views/{view}")
        assert "this.app.treeVersion" in src
        assert "this.app.treeWs" not in src


def test_grafo_abre_item_sem_depender_do_indice_da_sidebar():
    """`goTo` usava hItemById (precisa do item já estar no itemIndex, carregado pela
    sidebar) — abrir o grafo direto, sem antes expandir a gaveta daquele workspace, fazia o
    clique no nó não abrir nada. O próprio nó do grafo já traz project_id; usa direto."""
    graph = _js("views/graph.js")
    assert "goTo(n) {" in graph
    assert "hrefs.item(this.app.connId, ws, n.project_id, n.id)" in graph
    assert "hItemById" not in graph


def test_grafo_project_e_assunto_sao_nos_proprios_ligados_por_aresta_de_hierarquia():
    """Tentamos antes contorno desenhado ao redor do grupo + legenda separada (texto
    flutuando perto do cluster sempre descolava de grupos pequenos, três rodadas de ajuste
    fino nunca convergiram de verdade). A virada: project e assunto são nós do PRÓPRIO
    grafo — um quadrado por project, um triângulo por grupo de assunto — ligados aos itens
    por uma aresta de hierarquia. A física já clusteriza sozinha a partir dela: não precisa
    de grade nominal, força de agrupamento à parte, contorno nem legenda."""
    graph = _js("views/graph.js")
    assert "gcluster-label" not in graph
    assert "legendProjects" not in graph and "addShape" not in graph
    assert "hierarchyNodesAndEdges()" in graph
    assert "kind: 'project'" in graph and "kind: 'subject'" in graph
    assert "kind: 'hierarchy'" in graph
    assert "function hueOf(id)" in graph  # cor do nó, não de um contorno
    # forma por tipo de nó: quadrado (project), triângulo (assunto), círculo (item, como já era)
    assert "document.createElementNS(SVG_NS, 'rect')" in graph
    assert "document.createElementNS(SVG_NS, 'polygon')" in graph
    assert "document.createElementNS(SVG_NS, 'circle')" in graph
    # balde "sem assunto" só vira nó quando o project tem 2+ grupos; com 1 só, redundante
    assert "p.buckets.size >= 2" in graph
    # clicar no nó de project/assunto abre a página dele, não a de um item
    assert "hrefs.project(this.app.connId, ws, n.project_id)" in graph
    assert "hrefs.subject(this.app.connId, ws, n.project_id, n.subject_id)" in graph

    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8") + (
        STATIC / "index.html"
    ).read_text(encoding="utf-8")
    assert "graph-legend" not in css
    assert "gedge-hierarchy" in css


def test_grafo_de_um_project_so_pula_o_no_de_project_redundante():
    """No grafo de um project só (aberto a partir da página do project), um nó de project
    repetiria a própria página corrente — só os nós de assunto (se o project tiver 2+
    grupos) entram, ligados direto nos itens."""
    graph = _js("views/graph.js")
    assert "scope === 'graph'" in graph
    assert "scope !== 'graph' && scope !== 'project-graph'" in graph
    assert "scope === 'graph' ? projectNodeId : null" in graph


def test_grafo_rotulo_e_camada_propria_nunca_coberto_por_outro_no():
    """Nó (forma) e rótulo (texto) são dois elementos separados, em duas camadas: todas as
    formas primeiro, todos os rótulos depois — por ordem de pintura do SVG, uma forma nunca
    fica por cima do texto de um nó vizinho, não importa quão perto os dois fiquem. Só uma
    aresta pode passar por baixo de um rótulo (regra do usuário: "a única coisa que pode
    sobrepor são as arestas")."""
    graph = _js("views/graph.js")
    shapes_idx = graph.index("const nodeEls = allNodes.map")
    labels_idx = graph.index("const labelEls = allNodes.map")
    assert shapes_idx < labels_idx
    # project/assunto um pouco maiores que o item TÍPICO, não o teto raro de grau alto
    assert "const ITEM_TYPICAL_RADIUS = 9" in graph
    assert "RADIUS = { project: ITEM_TYPICAL_RADIUS * 1.1," in graph


def test_grafo_project_e_assunto_tem_cor_propria_nao_cinza():
    """`fill="..."` (atributo de apresentação) perde pra qualquer regra de CSS que declare
    `fill`, mesmo sem !important e nascida depois no documento — a regra `.gnode circle,
    .gnode rect, .gnode polygon { fill: var(--tc, var(--text-2)) }` sempre vencia o
    `fill` setado via JS, caindo no fallback cinza (`--text-2`) pra todo nó de project e
    assunto. Setar a própria variável `--tc` (que a regra já lê) resolve: variável CSS via
    `style` tem prioridade mais alta que a regra, então o fallback nunca entra em jogo."""
    graph = _js("views/graph.js")
    assert "g.style.setProperty('--tc'" in graph
    assert "shape.setAttribute('fill'" not in graph


def test_grafo_balde_sem_assunto_nao_escreve_sem_assunto():
    """O balde "sem assunto" (itens soltos de um project com 2+ grupos) continua um
    triângulo próprio — só não leva texto nenhum, nem a palavra "Sem assunto": é óbvio pela
    posição (ligado direto no project) sem precisar nomear."""
    graph = _js("views/graph.js")
    assert "'Sem assunto'" not in graph
    assert "n.subject_id ? n.subject_name : ''" in graph
    # `n.label || n.title` trocaria "" (falsy) pelo title errado — tem que checar undefined
    assert "n.label !== undefined ? n.label : n.title" in graph


def test_grafo_forma_de_project_e_assunto_compensa_area_pra_nao_parecer_maior():
    """No mesmo raio nominal, um quadrado tem ~27% mais área que um círculo (4r² contra
    πr²) — por isso, mesmo com RADIUS só 1.1x/1.05x do item, o quadrado/triângulo liam como
    bem maiores. O raio usado no layout (collide, link, posição do rótulo) não muda; só o
    desenho encolhe."""
    graph = _js("views/graph.js")
    assert "r * 0.82" in graph  # quadrado do project
    assert "r * 0.88" in graph  # triângulo do assunto


def test_grafo_tem_legenda_generica_de_forma_acima_do_canvas():
    """Não é a legenda por nome (removida — cada nó já se rotula agora); é uma legenda
    genérica, fixa, explicando o que cada FORMA significa (círculo = item, triângulo =
    assunto, quadrado = project) — acima do SVG, fora da física, nunca se move."""
    html = _index()
    block = html[html.index("<!-- Grafo") : html.index("<!-- Project -->")]
    assert 'class="graph-key"' in block
    key_idx = block.index('class="graph-key"')
    svg_idx = block.index('<svg class="graph-svg"')
    assert key_idx < svg_idx
    assert "gk-circle" in block and "gk-triangle" in block and "gk-square" in block
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8") + (
        STATIC / "index.html"
    ).read_text(encoding="utf-8")
    assert ".glabel {" in css and ".glabel-project, .glabel-subject {" in css


def test_grafo_nao_usa_template_x_for_dentro_de_svg():
    """`<template x-for>` filho de `<svg>` quebra: o navegador não dá o namespace SVG pro
    conteúdo do template, e o clone do Alpine falha em runtime (achado testando a UI de
    verdade, não só com asserção estática). O SVG é montado via DOM real
    (`createElementNS`/`textContent`), nunca `x-html`/`.innerHTML` — mesma regra de nunca
    gerar HTML bruto que vale pro resto do app (markdown.js é a única exceção, via
    DOMPurify)."""
    html = _index()
    block = html[html.index("<!-- Grafo") : html.index("<!-- Project -->")]
    # só dentro do próprio elemento <svg> importa pra esse bug — a legenda (fora do svg,
    # HTML comum) pode usar x-for à vontade, não tem namespace nenhum envolvido
    svg_start = block.index("<svg class=\"graph-svg\"")
    inside = block[svg_start : block.index("</svg>", svg_start)]
    assert "<template x-for" not in inside
    assert "x-html" not in inside
    assert 'x-effect="renderSvg($el)"' in inside
    graph = _js("views/graph.js")
    assert "renderSvg(svg)" in graph
    assert "createElementNS" in graph
    assert ".innerHTML" not in graph
    assert "byId.get(e.source)" in graph
    assert "edgeClass(e)" in graph and "nodeClass(n)" in graph
    # clique só conta se o nó não se mexeu entre mousedown e mouseup (senão todo drag
    # navegaria pro item ao soltar)
    assert "if (!moved) this.goTo(n)" in graph


def test_linhas_de_item_nao_usam_icone_de_tipo():
    html = _index()
    assert "$icon(" not in html
    rows = re.findall(r'<a class="item-row".*?</a>', html, re.S)
    assert rows
    for row in rows:
        # os únicos ícones da linha são os do badge (alerta, scope) e o da origem, todos
        # vindos do gerador: o tipo é bolinha + texto, nunca ícone
        assert row.count('x-for="b in $badges(it)"') == 1
        assert "<use href=" not in row
    util = (STATIC / "js" / "util.js").read_text(encoding="utf-8")
    type_badge = next(line for line in util.splitlines() if "key: 'type'" in line)
    assert "dot: true" in type_badge and "icon" not in type_badge


def _sidebar() -> str:
    html = _index()
    start = html.index("<!-- ===== Sidebar ===== -->")
    end = html.index("<!-- ===== Conteúdo ===== -->")
    return html[start:end]


def test_sidebar_so_tem_um_dropdown_o_da_connection():
    sidebar = _sidebar()
    assert sidebar.count('x-data="dropdown"') == 1
    assert 'dd-label">Workspace' not in sidebar  # sem o antigo label/dropdown de Workspace
    assert "pickWorkspace" not in sidebar


def test_sidebar_lista_todos_os_workspaces_como_gavetas():
    sidebar = _sidebar()
    assert "$store.app.workspaces" in sidebar
    assert "$store.app.hWs(w.id)" in sidebar


def test_sidebar_expande_e_recolhe_cada_workspace():
    sidebar = _sidebar()
    assert "isWorkspaceOpen" in sidebar and "toggleWorkspace" in sidebar
    store = _js("store.js")
    assert "isWorkspaceOpen(wsId)" in store and "toggleWorkspace(wsId)" in store


def test_sidebar_mostra_subjects_na_arvore():
    sidebar = _sidebar()
    assert "p.subjects" in sidebar

