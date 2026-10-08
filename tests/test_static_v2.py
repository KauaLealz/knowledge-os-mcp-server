"""Front no modelo v2 (V2_MVP.md §12), conferido nos arquivos de `api/static` (sem build):

- nenhum conceito do modelo antigo (labels, classe de memória, importância, confiança) como
  campo, rota ou texto de UI;
- os conceitos do v2 presentes (subtipo, scope com o herdado, origem, links, ⚠ de revisão,
  tags com contagem e gestão, caminho e saúde da conexão) e as rotas novas;
- todo `import` relativo resolve para um arquivo existente (import quebrado = tela branca).
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "knowledge_os" / "api" / "static"
OURS = [STATIC / "index.html", *sorted((STATIC / "js").rglob("*.js")),
        *sorted((STATIC / "css").glob("*.css"))]
# "label" sozinho é palavra comum de UI (aria-label, <label>, typeLabel): o conceito antigo é
# o plural, o id e a rota.
OLD = re.compile(r"memory_class|memoryClass|importance|confidence|\blabels\b|label_id", re.I)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _all() -> str:
    return "\n".join(_text(p) for p in OURS)


def test_nenhum_conceito_do_modelo_antigo():
    for path in OURS:
        for n, line in enumerate(_text(path).splitlines(), 1):
            hit = OLD.search(line)
            if not hit:
                continue
            raise AssertionError(f"{path.name}:{n}: {line.strip()}")


def test_campos_do_v2_presentes():
    text = _all()
    for needle in ("subtype", "scope", "effective_scope", "scope_inherited_from", "origin",
                   "links", "review", "ttl_days", "verified_at", "where"):
        assert needle in text, needle


def test_rotas_novas_da_api():
    js = "\n".join(_text(p) for p in (STATIC / "js").rglob("*.js"))
    for route in ("'/tags'", "/tags/", "/items/search", "/graph", "/feedback",
                  "/connections/health", "/subjects/", "'/workspaces'", "'/projects'"):
        assert route in js, route
    for gone in ("/relations`", "/stats`", "/labels"):
        assert gone not in js, gone


def test_tipos_com_subtipo_e_rotulos():
    util = _text(STATIC / "js" / "util.js")
    for t in ("rule", "howto", "context", "spec", "secret"):
        assert re.search(rf"^  {t}: \{{ label: ", util, re.M), t
    for st in ("decision", "troubleshoot", "environment", "dream", "security"):
        assert st in util, st
    for old in ("insight:", "knowledge:", "procedure: {", "pattern: {"):
        assert old not in util, old
    html = _text(STATIC / "index.html")
    assert html.count("$kind(it.type, it.subtype)") >= 5  # 3 listagens + 2 da árvore
    assert html.count("toggleSubtype(c.subtype)") == 3  # filtro de subtipo nas listagens
    assert "subtypesOf" in _text(STATIC / "js" / "views" / "editor.js")


def test_scope_com_herdado_indicado():
    util = _text(STATIC / "js" / "util.js")
    assert "inherited from" in util and "scope_inherited_from" in util
    html = _text(STATIC / "index.html")
    assert html.count("$iscope(it)") == 3 and "$iscope(item)" in html
    assert html.count('@change="setScope($event.target.value)"') == 3  # ws, project, subject
    for view in ("workspace", "project", "subject"):
        src = _text(STATIC / "js" / "views" / f"{view}.js")
        assert "get scopeInfo()" in src and "async setScope(value)" in src, view
        assert "scopeText(" in src, view


def test_review_marcado():
    html = _text(STATIC / "index.html")
    assert html.count("⚠ Review") >= 4  # 3 listagens + a página do item
    assert "item.status === 'review'" in html
    assert "isReview" in _text(STATIC / "js" / "views" / "listing.js")


def test_links_origin_e_ttl_no_item_e_no_editor():
    html = _text(STATIC / "index.html")
    assert 'x-for="l in item.links"' in html and 'rel="noopener noreferrer"' in html
    assert "$origin(item.origin)" in html and "$origin(origin)" in html
    assert 'x-model="draft.links"' in html and 'x-model="draft.ttl_days"' in html
    assert 'x-model="draft.subtype"' in html and 'x-model="draft.scope"' in html
    assert 'x-model="draft.origin"' not in html  # origin só leitura
    ed = _text(STATIC / "js" / "views" / "editor.js")
    assert "textToLinks" in ed and "'ttl_days'" in ed and "origin: 'user'" in ed


def test_tags_com_contagem_e_gestao():
    html = _text(STATIC / "index.html")
    block = html[html.index("<!-- Tags gerenciadas") : html.index("<!-- /Tags -->")]
    assert 'x-data="tagsView"' in block and "t.count" in block
    for action in ("create()", "rename()", "startRename(t)", "remove(t)", "Confirm: delete"):
        assert action in block, action
    tags = _text(STATIC / "js" / "views" / "tags.js")
    assert "'POST', '/tags'" in tags and "'PUT', `/tags/" in tags
    assert tags.count("'DELETE', `/tags/") == 2 and "confirm: 'true'" in tags
    assert "registerTags" in _text(STATIC / "js" / "main.js")
    assert "name: 'tags'" in _text(STATIC / "js" / "router.js")
    assert "hTags()" in html and 'href="#i-tag"' in html


def test_conexao_mostra_caminho_e_saude():
    html = _text(STATIC / "index.html")
    conn = html[html.index("<!-- Configurações · Conexões") :
                html.index("<!-- /Configurações · Conexões")]
    assert "c.path" in conn and "parseErrors(c)" in conn and "parseErrors(conn)" in conn
    assert "'/connections/health'" in _text(STATIC / "js" / "views" / "connections.js")


def test_grafo_le_o_formato_do_item_graph():
    graph = _text(STATIC / "js" / "views" / "graph.js")
    assert "source: e.from, target: e.to, relation_type: e.type" in graph
    item = _text(STATIC / "js" / "views" / "item.js")
    assert "/graph`" in item and "e.from === me" in item and "e.to === me" in item


def test_imports_relativos_resolvem():
    pattern = re.compile(r"(?:from|import)\s+'(\.{1,2}/[^']+)'")
    for path in (STATIC / "js").rglob("*.js"):
        if "vendor" in path.parts:
            continue
        for rel in pattern.findall(_text(path)):
            assert (path.parent / rel).resolve().is_file(), f"{path.name} -> {rel}"


def test_nomes_importados_existem_no_modulo():
    """`import { x } from './y.js'` com `x` que `y.js` não exporta também dá tela branca."""
    named = re.compile(r"import\s*\{([^}]*)\}\s*from\s*'(\.{1,2}/[^']+)'")
    for path in (STATIC / "js").rglob("*.js"):
        if "vendor" in path.parts:
            continue
        for names, rel in named.findall(_text(path)):
            target = (path.parent / rel).resolve()
            if "vendor" in target.parts:
                continue
            src = _text(target)
            for name in (n.strip().split(" as ")[0] for n in names.split(",") if n.strip()):
                assert re.search(rf"export (?:async )?(?:function|const|let|class) {name}\b",
                                 src), f"{path.name}: {name} de {rel}"


def test_magics_usadas_no_html_estao_registradas():
    html = _text(STATIC / "index.html")
    main = _text(STATIC / "js" / "main.js")
    for magic in set(re.findall(r"\$(kind|iscope|inherited|origin|stlabel|scopetext|tlabel|tc|"
                                r"ago)\(", html)):
        assert f"Alpine.magic('{magic}'" in main, magic


def test_data_components_usados_estao_registrados():
    html = _text(STATIC / "index.html")
    js = "\n".join(_text(p) for p in (STATIC / "js").rglob("*.js") if "vendor" not in p.parts)
    for comp in set(re.findall(r'x-data="(\w+)', html)):
        assert f"Alpine.data('{comp}'" in js, comp
