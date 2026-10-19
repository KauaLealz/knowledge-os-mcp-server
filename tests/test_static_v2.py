"""Front no modelo v6, conferido nos arquivos de `api/static` (sem build):

- nenhum conceito do modelo antigo (subtipo, scope, status, origin, feedback, ttl) como campo,
  rota ou controle de UI;
- os conceitos do v6 presentes (os 5 tipos, tags como nuance+ciclo, links unificados, filtro por
  tipo e tag, alcance por hierarquia, caminho e saúde da conexão);
- todo `import` relativo resolve para um arquivo existente (import quebrado = tela branca).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "knowledge_os" / "api" / "static"
OURS = [STATIC / "index.html", *sorted((STATIC / "js").rglob("*.js")),
        *sorted((STATIC / "css").glob("*.css"))]
# Conceitos removidos no v6: os do modelo antigo e os artefatos v2 (subtipo, scope com herança,
# status/review, origin, feedback, ttl). `scope()` da listagem é o filtro de localização, legítimo.
OLD = re.compile(r"memory_class|memoryClass|importance|confidence|\blabels\b|label_id|"
                 r"\bsubtype\b|\bsubtypes\b|effective_scope|scope_explicit|scope_inherited|"
                 r"scope_paths|scopeBadges|\$scopebadges|setScope|scopeInfo|statusesFor|"
                 r"subtypeLabel|\borigin\b|ttl_days|verified_at|item_feedback", re.I)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _all() -> str:
    return "\n".join(_text(p) for p in OURS)


def test_nenhum_conceito_do_modelo_antigo_nem_do_v2():
    for path in OURS:
        for n, line in enumerate(_strip_comments(_text(path)).splitlines(), 1):
            if line.strip() and OLD.search(line):
                raise AssertionError(f"{path.name}:{n}: {line.strip()}")


def test_campos_do_v6_presentes():
    text = _all()
    for needle in ("type", "tags", "links", "where", "depends_on", "relates_to"):
        assert needle in text, needle


def test_rotas_da_api():
    js = "\n".join(_text(p) for p in (STATIC / "js").rglob("*.js"))
    for route in ("'/tags'", "/tags/", "/items/search", "/graph",
                  "/connections/health", "'/workspaces'", "'/projects'"):
        assert route in js, route
    for gone in ("/feedback", "/relations`", "/stats`", "/labels"):
        assert gone not in js, gone


def test_cinco_tipos_sem_subtipo():
    util = _text(STATIC / "js" / "util.js")
    for t in ("rule", "howto", "context", "work", "secret"):
        assert re.search(rf"^  {t}: \{{ label: ", util, re.M), t
    for gone in ("insight:", "knowledge:", "spec:", "subtypes:", "SUBTYPE_LABELS", "SCOPES"):
        assert gone not in util, gone
    # O rótulo do tipo sai do gerador único (sem subtipo).
    assert "$kind(it.type)" in _text(STATIC / "index.html")
    assert "export function kindLabel" in util
    # Filtro por tag no lugar do subtipo, nas 3 listagens.
    assert _text(STATIC / "index.html").count("toggleTag(c.tag)") == 3
    assert "chipTags" in _text(STATIC / "js" / "views" / "listing.js")


def test_tags_carregam_nuance_e_ciclo():
    util = _text(STATIC / "js" / "util.js")
    for tag in ("decision", "troubleshoot", "security", "draft", "active", "done", "archived"):
        assert tag in util, tag
    assert "LIFECYCLE_TAGS" in util and "NUANCE_TAGS" in util


def test_links_unificados_no_item_e_no_editor():
    html = _text(STATIC / "index.html")
    assert 'x-for="l in item.links"' in html and 'rel="noopener noreferrer"' in html
    assert "$meta(item)" in html
    assert 'x-model="draft.links"' in html and 'x-model="draft.tags"' in html
    for gone in ('draft.subtype', 'draft.scope', 'draft.status', 'draft.ttl_days',
                 'draft.origin', '$origin('):
        assert gone not in html, gone
    ed = _text(STATIC / "js" / "views" / "editor.js")
    assert "textToLinks" in ed and "'subtype'" not in ed and "'scope'" not in ed


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


def test_sem_scope_em_lugar_nenhum():
    for path in _static_ours():
        text = _strip_comments(_text(path))
        for banned in ("Scoped", "Inherit", "setScope", "scopeInfo", "$scopebadges",
                       "Scope: ", "scope-pick"):
            assert banned not in text, f"{path.name}: {banned}"


def test_um_unico_gerador_de_badges_e_os_templates_so_o_percorrem():
    util = _text(STATIC / "js" / "util.js")
    assert util.count("export function itemBadges(") == 1
    assert "export function itemMeta(" in util
    assert "scopeBadges" not in util  # não há mais scope
    main = _text(STATIC / "js" / "main.js")
    for magic in ("badges", "meta", "connbadges", "faded"):
        assert f"Alpine.magic('{magic}'" in main, magic
    html = _text(STATIC / "index.html")
    # ninguém monta chip/badge à mão
    for path in _static_ours():
        if path.suffix in (".html", ".js"):
            text = _text(path)
            assert 'class="chip' not in text and "class=\"tbadge" not in text, path.name
            assert not re.search(r'class="badge[\s"]', text), path.name  # .badges é o contêiner
    css = _text(STATIC / "css" / "app.css")
    assert ".chip" not in css and ".tbadge" not in css and ".badge {" in css
    loops = BADGE_LOOP.findall(html)
    sources = [src for src, _ in loops]
    assert sum(s.startswith("$badges(it") for s in sources) >= 3, sources
    assert any(s.startswith("$badges(item)") for s in sources)
    assert any(s.startswith("$badges(e.it") for s in sources)  # paleta
    assert any(s.startswith("$connbadges(") for s in sources)  # conexões
    bodies = {body for _, body in loops}
    assert len(bodies) == 1, bodies  # o MESMO trecho de markup em todo lugar


def test_linhas_usam_badges_e_meta_e_where_so_onde_mistura_projects():
    html = _text(STATIC / "index.html")
    rows = re.findall(r'<a class="item-row".*?</a>', html, re.S)
    assert len(rows) == 3
    for row in rows:
        assert row.count('x-for="b in $badges(it)"') == 1
        assert "$meta(it" in row and "$origin(" not in row
    ws = html[html.index("<!-- Workspace -->") : html.index("<!-- Grafo")]
    pj = html[html.index("<!-- Project -->") : html.index("<!-- Item -->")]
    assert "$meta(it, { where: where(it) })" in ws
    assert "where(" not in pj  # dentro de project/subject o lugar já é a página


def test_crumbs_mostram_so_ancestrais():
    html = _text(STATIC / "index.html")
    for nav in re.findall(r'<nav class="crumbs">(.*?)</nav>', html, re.S):
        assert "<span x-text" not in nav and "<span>Graph</span>" not in nav, nav
        assert "<span>Tags</span>" not in nav, nav


def test_botao_so_de_icone_tem_aria_label_e_title():
    html = _text(STATIC / "index.html")
    attrs = r'(?:"[^"]*"|[^>"])*'
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


def _node(code: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    util = (STATIC / "js" / "util.js").as_uri()
    script = f"import * as u from {json.dumps(util)};\n{code}"
    out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                         text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(out.stdout)


def test_item_arquivado_fica_esmaecido():
    got = _node("""
console.log(JSON.stringify([u.isFaded({ tags: ['archived'] }),
  u.isFaded({ tags: ['active'] }), u.isFaded({})]));
""")
    assert got == [True, False, False]
    html = _text(STATIC / "index.html")
    tree = re.findall(r'<a class="tree-item"[^>]*>', html)
    assert len(tree) == 2 and all("faded: $faded(it)" in a for a in tree)


def test_lifecycle_badge_vem_da_tag():
    got = _node("""
const cls = (tags) => u.itemBadges({ type: 'work', tags }, { type: false }).map((b) => b.label);
console.log(JSON.stringify({
  draft: cls(['draft']), done: cls(['done']), archived: cls(['archived']),
  active: cls(['active']), none: cls([]),
}));
""")
    assert got["draft"] == ["Draft"]
    assert got["done"] == ["Done"]
    assert got["archived"] == ["Archived"]
    assert got["active"] == []  # active é o normal: sem badge
    assert got["none"] == []
