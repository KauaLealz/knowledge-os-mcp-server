"""A UI funciona sem internet: nada de CDN, tudo servido pelo próprio servidor (AC7)."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "knowledge_os" / "api" / "static"
VENDOR = ("alpine.esm.js", "marked.esm.js", "purify.esm.js", "highlight.esm.js")


def test_html_e_js_nao_carregam_nada_de_fora():
    for path in [STATIC / "index.html", *STATIC.glob("js/**/*.js")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(src|href|from|import)\s*[=(]?\s*['\"]https?://", text), path


def test_sem_script_inline_nem_importmap():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "importmap" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)


def test_bibliotecas_servidas_localmente(client):
    for name in VENDOR:
        res = client.get(f"/ui/vendor/{name}")
        assert res.status_code == 200 and "export" in res.text, name


def test_csp_so_permite_scripts_locais(client):
    csp = client.get("/ui/").headers["Content-Security-Policy"]
    assert "script-src 'self' 'unsafe-eval'" in csp and "default-src 'self'" in csp
    assert "http" not in csp


def test_ui_pede_revalidacao_para_nao_misturar_versoes_em_cache(client):
    for path in ("/ui/", "/ui/js/main.js", "/ui/vendor/alpine.esm.js"):
        assert client.get(path).headers["Cache-Control"] == "no-cache", path
