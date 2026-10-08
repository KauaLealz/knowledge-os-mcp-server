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
    # o rótulo "Rule · Decision" sai do gerador único de badges (e do sr-only da árvore)
    assert "kindLabel(it.type, it.subtype)" in util
    html = _text(STATIC / "index.html")
    assert html.count("toggleSubtype(c.subtype)") == 3  # filtro de subtipo nas listagens
    assert "subtypesOf" in _text(STATIC / "js" / "views" / "editor.js")


def test_scope_com_herdado_indicado():
    util = _text(STATIC / "js" / "util.js")
    assert "Inherited from" in util and "scope_inherited_from" in util
    assert "badge scope inherited" in util  # herdado = tracejado, com tooltip de onde vem
    html = _text(STATIC / "index.html")
    assert "$badges(item" in html
    assert html.count('@change="setScope($event.target.value)"') == 3  # ws, project, subject
    for view in ("workspace", "project", "subject"):
        src = _text(STATIC / "js" / "views" / f"{view}.js")
        assert "get scopeInfo()" in src and "async setScope(value)" in src, view
        assert "inheritedNote(" in src, view


def test_review_marcado():
    util = _text(STATIC / "js" / "util.js")
    assert "review: { label: 'Review'" in util and "icon: 'alert'" in util
    html = _text(STATIC / "index.html")
    # a ficha mostra o banner curto; o badge ⚠ Review fica nas listas e na árvore
    assert "item.status === 'review'" in html and "$badges(item, { review: false })" in html
    assert "isReview" in _text(STATIC / "js" / "views" / "listing.js")


def test_links_origin_e_ttl_no_item_e_no_editor():
    html = _text(STATIC / "index.html")
    assert 'x-for="l in item.links"' in html and 'rel="noopener noreferrer"' in html
    assert "$meta(item)" in html and "$origin(origin)" in html
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
    conn = html[html.index("<!-- Settings · Connections") :
                html.index("<!-- /Settings · Connections")]
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
    for magic in set(re.findall(r"\$([a-z]+)\(", html)):
        if magic in ("event", "el", "refs", "store", "watch", "nextTick", "dispatch"):
            continue
        assert f"Alpine.magic('{magic}'" in main, magic


def test_data_components_usados_estao_registrados():
    html = _text(STATIC / "index.html")
    js = "\n".join(_text(p) for p in (STATIC / "js").rglob("*.js") if "vendor" not in p.parts)
    for comp in set(re.findall(r'x-data="(\w+)', html)):
        assert f"Alpine.data('{comp}'" in js, comp


# ---- sistema de badges, redundâncias e idioma ----
BADGE_LOOP = re.compile(
    r'<template x-for="b in (\$[a-z]+\([^"]*\))" :key="b\.key">(.*?)</template>', re.S
)


def _static_ours() -> list[Path]:
    return [p for p in STATIC.rglob("*") if p.is_file() and "vendor" not in p.parts]


def test_sem_scope_padrao_nem_not_set():
    for path in _static_ours():
        text = _text(path)
        for banned in ("Scoped (default)", "Not set (inherit)", "Not set (scoped)",
                       "(default)'", "Scope: "):
            assert banned not in text, f"{path.name}: {banned}"


def test_um_unico_gerador_de_badges_e_os_templates_so_o_percorrem():
    util = _text(STATIC / "js" / "util.js")
    assert util.count("export function itemBadges(") == 1
    assert "export function itemMeta(" in util and "export function scopeBadges(" in util
    main = _text(STATIC / "js" / "main.js")
    for magic in ("badges", "meta", "scopebadges", "connbadges", "faded"):
        assert f"Alpine.magic('{magic}'" in main, magic
    html = _text(STATIC / "index.html")
    # ninguém monta chip/badge à mão: nem a gramática antiga, nem a classe nova literal
    for path in _static_ours():
        if path.suffix in (".html", ".js"):
            text = _text(path)
            assert 'class="chip' not in text and "class=\"tbadge" not in text, path.name
            assert not re.search(r'class="badge[\s"]', text), path.name  # .badges é o contêiner
    css = _text(STATIC / "css" / "app.css")
    assert ".chip" not in css and ".tbadge" not in css and ".badge {" in css
    loops = BADGE_LOOP.findall(html)
    sources = [src for src, _ in loops]
    # 3 listagens + paleta + ficha + 2 da árvore + relações + cards + 3 toolbars? (não) + conexões
    assert sum(s.startswith("$badges(it") for s in sources) >= 5, sources
    assert any(s.startswith("$badges(item, { review: false })") for s in sources)
    assert any(s.startswith("$badges(e.it") for s in sources)  # paleta
    assert any(s.startswith("$scopebadges(") for s in sources)  # cards de workspace
    assert any(s.startswith("$connbadges(") for s in sources)  # conexões
    bodies = {body for _, body in loops}
    assert len(bodies) == 1, bodies  # o MESMO trecho de markup em todo lugar


def test_linhas_usam_badges_e_meta_e_where_so_onde_mistura_projects():
    html = _text(STATIC / "index.html")
    rows = re.findall(r'<a class="item-row".*?</a>', html, re.S)
    assert len(rows) == 3
    for row in rows:
        assert row.count('x-for="b in $badges(it)"') == 1
        assert "$meta(it" in row and "$origin(" not in row and "$ago(" not in row
    ws = html[html.index("<!-- Workspace -->") : html.index("<!-- Grafo")]
    pj = html[html.index("<!-- Project -->") : html.index("<!-- Item -->")]
    assert "$meta(it, { where: where(it) })" in ws
    assert "where(" not in pj  # dentro de project/subject o lugar já é a página


def test_crumbs_mostram_so_ancestrais():
    html = _text(STATIC / "index.html")
    for nav in re.findall(r'<nav class="crumbs">(.*?)</nav>', html, re.S):
        # a página atual nunca vira crumb (já é o H1): nada de <span x-text=...> nem texto fixo
        assert "<span x-text" not in nav and "<span>Graph</span>" not in nav, nav
        assert "<span>Tags</span>" not in nav, nav


def test_scope_e_um_controle_so_com_ajuda_quando_herdado():
    html = _text(STATIC / "index.html")
    assert html.count('class="scope-pick"') == 3
    for block in re.findall(r'<label class="scope-pick">(.*?)</label>', html, re.S):
        assert "<select" in block and ">Scope<" in block
        assert "scopeInfo.note" in block  # "Inherited from workspace" só quando herdado


def test_botao_so_de_icone_tem_aria_label_e_title():
    html = _text(STATIC / "index.html")
    attrs = r'(?:"[^"]*"|[^>"])*'  # valor entre aspas pode ter ">" (ex.: page >= totalPages)
    buttons = re.findall(rf'<(?:button|a)\b{attrs}class="btn icon[^"]*"{attrs}>', html)
    assert len(buttons) >= 10
    for b in buttons:
        assert re.search(r'(?<![\w-]):?aria-label=', b), b
        assert re.search(r'(?<![\w-]):?title=', b), b


PT_WORDS = re.compile(
    r"\b(Conex(?:ão|ões|oes)|Configura(?:ções|coes)|Padrão|Nunca|Repositório|Pasta|Salvar|"
    r"Testar|Apagar|Voltar|Cancelar|Nenhuma?|Ativa|Desativada|Direto|Modo|Ações|Zona|"
    r"Erro|Falhou|Itens|Filtros|vizinhos|arquivo|ilegível|só local|sem remote|caminho|"
    r"Opcional|Definir|nesta|máquina|recarregue|Depois|ferramenta)\b")


def _strip_comments(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(^|\s)//.*$", r"\1", text, flags=re.M)


def test_ui_toda_em_ingles():
    for path in [STATIC / "index.html", *(STATIC / "js").rglob("*.js")]:
        if "vendor" in path.parts:
            continue
        for n, line in enumerate(_strip_comments(_text(path)).splitlines(), 1):
            hit = PT_WORDS.search(line)
            assert not hit, f"{path.name}: {hit.group(0)!r} em {line.strip()[:120]}"


def _hex(color: str) -> list[float]:
    color = color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(color[i : i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _contrast(a: str, b: str) -> float:
    la, lb = (0.2126 * r + 0.7152 * g + 0.0722 * bl for r, g, bl in (_hex(a), _hex(b)))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_texto_secundario_tem_contraste_aa_nos_dois_temas():
    tokens = _text(STATIC / "css" / "tokens.css")
    light = tokens[: tokens.index("@media (prefers-color-scheme: dark)")]
    dark = tokens[tokens.index(':root[data-theme="dark"]') :]

    def tok(block: str, name: str) -> str:
        return re.search(rf"--{name}: (#[0-9a-fA-F]{{6}});", block).group(1)

    for block in (light, dark):
        for fg in ("text-2", "text-3", "warn-text", "accent-text", "danger"):
            for bg in ("bg", "bg-soft", "bg-hover"):
                ratio = _contrast(tok(block, fg), tok(block, bg))
                assert ratio >= 4.5, f"{fg} sobre {bg}: {ratio:.2f}"
