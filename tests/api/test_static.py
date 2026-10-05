"""Front estático em /ui/: servido sem autenticação, sem build step e sem Tailwind."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

STATIC = Path(__file__).resolve().parents[2] / "src" / "api" / "static"

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
    assert 'type="importmap"' in resp.text


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


def test_campo_de_senha_so_na_view_de_conexoes():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert CONN_OPEN in html and CONN_CLOSE in html
    inside = html[html.index(CONN_OPEN):html.index(CONN_CLOSE)]
    assert html.count('type="password"') == inside.count('type="password"') == 1
    assert 'autocomplete="new-password"' in inside
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
    for f in STATIC.rglob("*.js"):
        txt = f.read_text(encoding="utf-8")
        assert "Authorization" not in txt and "sessionStorage" not in txt, f.name
        assert "#token" not in txt and "captureToken" not in txt, f.name


def _js(name: str) -> str:
    return (STATIC / "js" / name).read_text(encoding="utf-8")


def test_markdown_passa_pelo_dompurify_e_nunca_por_x_html():
    md = _js("markdown.js")
    assert "DOMPurify.sanitize" in md and "marked" in md and "hljs" in md
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
