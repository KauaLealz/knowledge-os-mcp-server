"""Renderização de markdown no front (V2_MVP §12): mermaid, math (KaTeX), quebra de linha,
HTML inline, checkbox da lista de tarefas. Conferido nos arquivos servidos de `api/static` —
o comportamento em si é provado dirigindo o painel no navegador. Mantém a regra do projeto:
sem CDN, tudo vendorizado sob `static/vendor/` (servido de 'self' pela CSP)."""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "knowledge_os" / "api" / "static"
VENDOR = STATIC / "vendor"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_vendor_mermaid_e_katex_presentes():
    """Libs novas vendorizadas (sem CDN): o painel não busca nada de fora."""
    assert (VENDOR / "mermaid.esm.js").is_file()
    assert (VENDOR / "marked-katex.esm.js").is_file()
    css = VENDOR / "katex" / "katex.min.css"
    assert css.is_file()
    fonts = list((VENDOR / "katex" / "fonts").glob("*.woff2"))
    assert fonts, "KaTeX precisa das fontes woff2 vendorizadas"
    # A CSS do KaTeX referencia woff2; essas fontes têm de existir localmente.
    assert "woff2" in _text(css)


def test_css_do_katex_ligado_no_index():
    assert 'vendor/katex/katex.min.css' in _text(STATIC / "index.html")


def test_markdown_js_fia_as_novas_capacidades():
    md = _text(STATIC / "js" / "markdown.js")
    # Quebra de linha simples vira <br>.
    assert "breaks: true" in md
    # KaTeX via extensão do marked (import + uso).
    assert "marked-katex.esm.js" in md
    assert "markedKatex(" in md
    # Mermaid carregado sob demanda e com securityLevel estrito.
    assert "vendor/mermaid.esm.js" in md
    assert "securityLevel: 'strict'" in md


def test_sanitizador_abre_so_o_necessario_sem_perder_xss():
    md = _text(STATIC / "js" / "markdown.js")
    # `input` deixou de ser barrado (checkbox da lista de tarefas), mas vira checkbox
    # desabilitado; `style` não é mais removido (o KaTeX posiciona com style).
    forbid_tags = md.split("FORBID_TAGS")[1].split("]")[0]
    forbid_attr = md.split("FORBID_ATTR")[1].split("]")[0]
    assert "'input'" not in forbid_tags  # input liberado (vira checkbox desabilitado)
    assert "'form'" in forbid_tags  # segue barrando formulário
    assert "'style'" not in forbid_attr  # style liberado p/ katex
    assert "getAttribute('type') !== 'checkbox'" in md  # restringe input a checkbox
    # O SVG do mermaid é sanitizado à parte, com perfil SVG.
    assert "USE_PROFILES" in md and "svg: true" in md
