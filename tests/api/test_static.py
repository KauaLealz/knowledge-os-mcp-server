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
    # Sem token: a rota existe e responde 401 (não 404 do mount estático).
    assert ui.get("/api/workspaces").status_code == 401


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


def test_html_sem_campo_de_senha():
    assert 'type="password"' not in (STATIC / "index.html").read_text(encoding="utf-8")


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


def test_token_e_lido_do_fragmento_e_nao_do_storage_persistente():
    api_js = (STATIC / "js" / "api.js").read_text(encoding="utf-8")
    assert "sessionStorage" in api_js and "replaceState" in api_js
    assert "localStorage" not in api_js


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
    assert "Sessão expirada" in html and "knowledge-mcp ui" in html
    # a falha de listagem aparece também na página de Workspace, não só na lista da conexão
    assert html.count("$store.app.wsError") >= 3
    assert "Tentar de novo" in html and 'role="alert"' in html


def test_sessao_expirada_sem_token_responde_401(ui):
    assert ui.get("/api/workspaces/x/tree").status_code == 401
