"""Achados da revisão de segurança da v2: cada teste reproduz o cenário de falha descrito.

Bloqueadores: segredo herdando scope de outro contexto; credencial em `links`/`source`.
Majors: ReDoS em `scope_paths`; bomba de YAML e `repr` enorme nas mensagens; lote não atômico
diante de erro de I/O; colisão de arquivo no Windows (caixa, ponto final, nome reservado);
merge/delete mudando o alcance de quem herdava. (A fila offline envenenada está em
`test_cli_brain.py`; o corpo da API sobrescrevendo a rota, em `api/test_items_corpo.py`.)
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import time
from datetime import datetime

import pytest

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import check_links, validate_entry
from knowledge_os.services import item_file
from knowledge_os.services.brain import Brain, read_metas
from knowledge_os.services.context_service import ContextService
from knowledge_os.services.item_file import parse_item_file
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.repo_service import RepoService
from knowledge_os.services.secret_service import SecretService
from knowledge_os.services.subject_service import SubjectService
from knowledge_os.services.workspace_service import WorkspaceService
from knowledge_os.storage import local_state
from knowledge_os.storage.files import FileStore, ItemRecord
from knowledge_os.storage.search import paths_match

VALUE = "npm_Zx81kQ2pL0aVb7Yt3Rw9Mn4C"  # não casa com nenhum padrão do secret_guard
OTHER = "github.com/cliente/app"


def _rule(ws, pj, key="rule/x", subject=None, **extra):
    entry = {"workspace": ws, "project": pj, "key": key, "type": "rule", "title": f"T {key}",
             "summary": "s", "content": "c", **extra}
    if subject:
        entry["subject"] = subject
    return ItemService().save([entry])[0]["id"]


def _secret(ws, pj, key="secret/github-token", value=VALUE, **extra):
    out = ItemService().save([{"workspace": ws, "project": pj, "key": key, "type": "secret",
                               "title": "Token do GitHub", "summary": "Publicar no GitHub",
                               **extra}])
    SecretService().set_value(out[0]["id"], value)
    return out[0]["id"]


def _record(item_id):
    return Brain().snapshot.require(item_id)


def _effective(item_id):
    snap = Brain().snapshot
    return snap.effective_scope(snap.require(item_id))


def _tree(root):
    """{path relativo: bytes} dos arquivos da pasta (fora do `.git`)."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


# ============================================================ bloqueador 1: segredo e scope


@pytest.fixture
def pessoal_global(conn):
    """Workspace `Pessoal` com scope global e um repositório de outro cliente ligado."""
    WorkspaceService().create("Pessoal", scope="global")
    ProjectService().create("pessoal", "notas")
    RepoService().link(OTHER, "Cliente", "app")
    return conn


def test_segredo_nao_herda_o_scope_global_do_workspace(pessoal_global):
    item_id = _secret("Pessoal", "notas")
    rule_id = _rule("Pessoal", "notas", "rule/comum")
    with pytest.raises(NotFoundError):
        SecretService().resolve(OTHER, "secret/github-token")
    assert "Token do GitHub" not in ContextService().build(OTHER)["markdown"]
    row = ItemService().get_many(ids=[item_id])[0]
    assert (row["scope"], row["scope_explicit"]) == ("scoped", None)
    assert _effective(item_id) == "scoped"
    assert _effective(rule_id) == "global"  # o resto continua herdando


def test_segredo_com_scope_global_explicito_resolve_de_outro_workspace(pessoal_global):
    item_id = _secret("Pessoal", "notas", scope="global")
    item, value = SecretService().resolve(OTHER, "secret/github-token")
    assert (item.id, value) == (item_id, VALUE)
    assert "Token do GitHub" in ContextService().build(OTHER)["markdown"]


def test_segredo_do_project_do_repo_vence_o_de_fora(pessoal_global):
    _secret("Pessoal", "notas", scope="global")
    local = _secret("Cliente", "app", value="local-" + VALUE)
    item, value = SecretService().resolve(OTHER, "secret/github-token")
    assert (item.id, value) == (local, "local-" + VALUE)


def test_dois_segredos_igualmente_proximos_sao_ambiguos(pessoal_global):
    _secret("Pessoal", "notas", scope="global")
    WorkspaceService().create("Outro")
    ProjectService().create("outro", "x")
    _secret("Outro", "x", scope="global")
    with pytest.raises(ValidationError, match="mais de um lugar") as exc:
        SecretService().resolve(OTHER, "secret/github-token")
    assert VALUE not in str(exc.value)


# ============================================================ bloqueador 2: credencial em campos


@pytest.mark.parametrize("extra", [
    {"links": [{"title": "Painel", "url": "https://admin:S3nh4@host.com/x"}]},
    {"links": [{"title": "API", "url": "https://api.host.com/v1?api_key=sk-abcdefghijklmnopqrstuvwx"}]},
    {"links": [{"title": "https://admin:S3nh4@host.com", "url": "https://host.com"}]},
    {"source": "https://admin:S3nh4@host.com/ticket"},
    {"scope_paths": ["src/sk-abcdefghijklmnopqrstuvwx/*"]},
])
def test_credencial_em_links_source_e_scope_paths_e_recusada(conn, data_dir, extra):
    with pytest.raises(ValidationError) as exc:
        ItemService().save([{"workspace": "W", "project": "P", "key": "context/painel",
                             "type": "context", "title": "Painel", "summary": "s", **extra}])
    msg = str(exc.value)
    assert "S3nh4" not in msg and "sk-abc" not in msg
    assert "tire a credencial" in msg and "secret" in msg
    assert not list(data_dir.rglob("*.md"))


@pytest.mark.parametrize("url", ["javascript:alert(1)", "JavaScript:alert(1)",
                                 "data:text/html,<b>x</b>", "file:///etc/passwd",
                                 "ftp://host/x", "sem-esquema/doc"])
def test_link_com_esquema_nao_aceito_e_recusado(url):
    with pytest.raises(ValidationError, match="http, https, mailto"):
        check_links([{"title": "x", "url": url}])


def test_links_http_https_e_mailto_sao_aceitos():
    urls = ["http://a.com", "https://a.com/x?y=1", "mailto:dev@a.com"]
    assert [lk["url"] for lk in check_links([{"url": u} for u in urls])] == urls


# ============================================================ major 4: colisões no Windows


def test_key_que_difere_so_pela_caixa_e_recusada(conn, data_dir):
    first = _rule("W", "P", "rule/money")
    before = _tree(data_dir)
    with pytest.raises(ValidationError, match=r"já existe `rule/money` \(a caixa não diferencia\)"):
        _rule("W", "P", "Rule/Money")
    assert _tree(data_dir) == before
    assert _record(first).key == "rule/money"


def test_mover_para_project_com_a_mesma_key_em_outra_caixa_e_recusado(conn):
    _rule("W", "P", "rule/money")
    other = _rule("W", "Q", "Rule/Money")
    with pytest.raises(ValidationError, match="a caixa não diferencia"):
        ItemService().save([{"id": other, "workspace": "W", "project": "P"}])


@pytest.mark.parametrize("key", ["rule./money", "rule/money.", "rule/con", "rule/nul.txt",
                                 "COM1/x", "rule/lpt9", "Aux/regra"])
def test_key_que_o_windows_nao_guarda_e_recusada(conn, key):
    with pytest.raises(ValidationError, match="Windows"):
        _rule("W", "P", key)


@pytest.mark.parametrize("name", ["con", "Aux", "acme.", "lpt1.txt", "COM9"])
def test_nome_reservado_ou_com_ponto_final_e_recusado(conn, name):
    with pytest.raises(ValidationError, match="Windows"):
        WorkspaceService().create(name)
    WorkspaceService().create("W")
    with pytest.raises(ValidationError, match="Windows"):
        ProjectService().create("w", name)
    ProjectService().create("w", "P")
    with pytest.raises(ValidationError, match="Windows"):
        SubjectService().create("w", "p", name)
    with pytest.raises(ValidationError, match="Windows"):
        _rule("W", "P", "rule/ok", subject=name)


def test_rascunho_compara_os_caminhos_sem_caixa(conn):
    first = _rule("W", "P", "rule/money")
    brain = Brain()
    with brain.editing() as d:
        d.put(dataclasses.replace(d.require(first), id="outro-id", key="Rule/Money",
                                  path=""))
        with pytest.raises(ValidationError, match="mesmo arquivo"):
            d.files()


# ============================================================ major 3: lote atômico


def test_caminho_longo_demais_e_recusado_antes_de_tocar_o_disco(conn, data_dir, monkeypatch):
    _rule("W", "P", "rule/money")
    _rule("W", "P", "rule/outra")
    before, head = _tree(data_dir), _git(data_dir, "rev-parse", "HEAD")
    monkeypatch.setattr(item_file, "MAX_PATH_CHARS", len(str(data_dir.resolve())) + 60)
    with pytest.raises(ValidationError, match="caminho longo demais"):
        WorkspaceService().update("W", new_name="x" * 120)
    assert _tree(data_dir) == before
    assert _git(data_dir, "rev-parse", "HEAD") == head
    assert _git(data_dir, "status", "--porcelain") == ""


def test_falha_de_escrita_no_meio_do_lote_restaura_a_pasta(conn, data_dir, monkeypatch):
    import knowledge_os.services.git_repo_service as grs

    a, b = _rule("W", "P", "rule/money"), _rule("W", "P", "rule/outra")
    before, head = _tree(data_dir), _git(data_dir, "rev-parse", "HEAD")
    real = os.replace
    calls = []

    def flaky(src, dst):
        if str(data_dir) in str(dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disco cheio")
        return real(src, dst)

    monkeypatch.setattr(grs.os, "replace", flaky)
    with pytest.raises(OSError, match="disco cheio"):
        WorkspaceService().update("W", new_name="Novo")
    monkeypatch.setattr(grs.os, "replace", real)
    assert len(calls) == 2
    assert _tree(data_dir) == before
    assert _git(data_dir, "rev-parse", "HEAD") == head
    assert _git(data_dir, "status", "--porcelain") == ""
    snap = Brain().snapshot
    assert {snap.require(a).workspace, snap.require(b).workspace} == {"W"}


# ============================================================ major 2: YAML e mensagens


def _bomb(levels: int) -> str:
    names = "abcdefghij"[:levels]
    lines = [f"{names[0]}: &{names[0]} [" + ", ".join(['"lol"'] * 9) + "]"]
    for prev, cur in zip(names, names[1:], strict=False):
        lines.append(f"{cur}: &{cur} [" + ", ".join([f"*{prev}"] * 9) + "]")
    return ("---\n" + "\n".join(lines) + f"\nid: bomba\ntype: rule\ntitle: *{names[-1]}\n"
            "summary: s\nstatus: active\ncreated_at: 2026-01-01T00:00:00Z\n"
            "updated_at: 2026-01-01T00:00:00Z\n---\ncorpo\n")


def test_frontmatter_com_alias_yaml_e_recusado_com_mensagem_curta():
    with pytest.raises(ValidationError, match="alias YAML não é aceito") as exc:
        parse_item_file(_bomb(5))
    assert len(str(exc.value)) < 300


def test_bomba_de_yaml_vira_erro_do_arquivo_e_o_resto_segue(conn, data_dir):
    keep = _rule("W", "P", "rule/money")
    bomb = data_dir / "w" / "p" / "rule" / "bomba.md"
    bomb.write_text(_bomb(9), encoding="utf-8")
    start = time.perf_counter()
    brain = Brain()
    assert time.perf_counter() - start < 5
    assert "alias YAML" in brain.store.errors["w/p/rule/bomba.md"]
    assert brain.snapshot.require(keep).key == "rule/money"
    _rule("W", "P", "rule/depois")  # gravar continua funcionando
    assert len(Brain().snapshot.records) == 2


def test_mensagem_de_erro_corta_o_valor_do_frontmatter():
    big = "[" + ", ".join(f'"valor-{i}"' for i in range(5000)) + "]"
    raw = (f"---\nid: x1\ntype: rule\ntitle: {big}\nsummary: s\nstatus: active\n"
           "created_at: 2026-01-01T00:00:00Z\nupdated_at: 2026-01-01T00:00:00Z\n---\n")
    with pytest.raises(ValidationError) as exc:
        parse_item_file(raw)
    assert "title" in str(exc.value) and len(str(exc.value)) < 300


def test_arquivo_de_item_grande_demais_nao_e_lido(tmp_path):
    root = tmp_path / "dados"
    (root / "w" / "p").mkdir(parents=True)
    (root / "w" / "p" / "grande.md").write_bytes(b"x" * ((1 << 20) + 1))
    store = FileStore(root)
    assert "grande demais" in store.errors["w/p/grande.md"]


def test_knowledge_yaml_grande_ou_com_alias_e_ignorado_com_erro(conn, data_dir):
    _rule("W", "P", "rule/money")
    (data_dir / "w" / ".knowledge.yaml").write_bytes(b"name: W\n" + b"#" * (256 * 1024))
    (data_dir / "w" / "p" / ".knowledge.yaml").write_text(
        "a: &a [1, 2]\nname: P\nb: *a\n", encoding="utf-8")
    errors: dict[str, str] = {}
    metas = read_metas(data_dir, errors)
    assert metas["w/.knowledge.yaml"] == {} and metas["w/p/.knowledge.yaml"] == {}
    assert "grande demais" in errors["w/.knowledge.yaml"]
    assert "alias YAML" in errors["w/p/.knowledge.yaml"]
    from knowledge_os.services.connection_service import ConnectionService

    paths = {e["path"] for e in ConnectionService().health()[0]["parse_errors"]}
    assert {"w/.knowledge.yaml", "w/p/.knowledge.yaml"} <= paths


def test_memory_error_ao_ler_um_arquivo_nao_derruba_a_leitura(tmp_path, monkeypatch):
    import knowledge_os.storage.files as files

    root = tmp_path / "dados"
    (root / "w").mkdir(parents=True)
    (root / "w" / "a.md").write_text("---\nx: 1\n---\n", encoding="utf-8")

    def boom(raw):
        raise MemoryError

    monkeypatch.setattr(files, "parse_item_file", boom)
    store = FileStore(root)
    assert "MemoryError" in store.errors["w/a.md"]


# ============================================================ major 1: ReDoS em scope_paths


def _rec(scope_paths) -> ItemRecord:
    return ItemRecord(
        id="r1", key="rule/r1", workspace="W", project="P", subject=None, type="rule",
        subtype=None, scope=None, title="t", status="active", tags=[], links=[],
        scope_paths=scope_paths, ttl_days=None, keywords=None, source=None, origin="agent",
        verified_at=None, verified_commit=None, created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1), relations=[], summary="s", content="",
    )


def test_glob_patologico_nao_trava_a_busca():
    path = "/".join(["a"] * 40) + "/" + "b" * 40
    for pattern in ("**/*?*?*?*?*?*?*?*?*?*?#", "*?" * 60 + "#", "**/" * 30 + "*" * 50 + "#"):
        start = time.perf_counter()
        assert not paths_match(_rec([pattern]), [path])
        assert not paths_match(_rec([path]), [pattern])
        assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize("pattern,path,expected", [
    ("src/**/*.py", "src/x.py", True),
    ("src/**/*.py", "src/a/b/c.py", True),
    ("src/**/*.py", "lib/a.py", False),
    ("docs/**", "docs", True),
    ("docs/**", "docs/a/b.md", True),
    ("*.md", "a/b.md", False),
    ("*.md", "b.md", True),
    ("src/?.py", "src/a.py", True),
    ("src/?.py", "src/ab.py", False),
    ("app/[id]/page.tsx", "app/[id]/page.tsx", True),
    ("src/**.py", "src/a/b.py", True),
    ("**", "qualquer/coisa", True),
])
def test_glob_mantem_o_casamento(pattern, path, expected):
    assert paths_match(_rec([pattern]), [path]) is expected


@pytest.mark.parametrize("paths,limit", [
    ([f"src/{i}/*" for i in range(21)], "no máximo 20"),
    (["a" * 201], "200 caracteres"),
    (["*?" * 4 + "*"], "8 curingas"),
])
def test_scope_paths_fora_do_limite_e_recusado(paths, limit):
    with pytest.raises(ValidationError, match=limit):
        validate_entry({"scope_paths": paths})


# ============================================================ major 5: merge/delete e scope


def test_apagar_subject_scoped_num_workspace_global_preserva_o_alcance(conn, data_dir):
    from knowledge_os.mcp import tools

    WorkspaceService().create("W", scope="global")
    ProjectService().create("w", "P")
    SubjectService().create("w", "p", "segredos", scope="scoped")
    a = _rule("W", "P", "rule/a", subject="segredos")
    b = _rule("W", "P", "rule/b")
    sec = _secret("W", "P", subject="segredos")
    preview = tools.subject_delete("W", "P", "segredos")
    assert preview["status"] == "preview" and preview["scope_changes"] == {"items": 1}
    assert _record(a).scope is None  # a prévia não muda nada
    commits = int(_git(data_dir, "rev-list", "--count", "HEAD"))
    tools.subject_delete("W", "P", "segredos", confirm=True)
    assert int(_git(data_dir, "rev-list", "--count", "HEAD")) == commits + 1
    assert (_record(a).scope, _effective(a)) == ("scoped", "scoped")
    assert (_record(b).scope, _effective(b)) == (None, "global")
    assert (_record(sec).scope, _effective(sec)) == (None, "scoped")


def test_mesclar_subject_mantem_o_alcance_dos_itens(conn):
    WorkspaceService().create("W")
    ProjectService().create("w", "P")
    SubjectService().create("w", "p", "git", scope="global")
    SubjectService().create("w", "p", "outros")
    a = _rule("W", "P", "rule/a", subject="git")
    out = SubjectService().merge("w", "p", "git", "outros")
    assert out["scope_changes"] == {"items": 1}
    assert (_record(a).scope, _effective(a)) == ("global", "global")


def test_mesclar_workspace_global_em_scoped_mantem_as_regras_globais(conn):
    WorkspaceService().create("Global", scope="global")
    ProjectService().create("global", "Geral")
    WorkspaceService().create("Cliente")
    ProjectService().create("cliente", "app")
    g = _rule("Global", "Geral", "rule/g")
    s = _rule("Global", "Geral", "rule/s", scope="workspace")
    sec = _secret("Global", "Geral")
    out = WorkspaceService().merge("Global", "Cliente")
    assert out["scope_changes"] == {"items": 1}
    assert (_record(g).workspace, _record(g).scope, _effective(g)) == ("Cliente", "global",
                                                                        "global")
    assert _record(s).scope == "workspace"
    assert (_record(sec).scope, _effective(sec)) == (None, "scoped")


def test_mesclar_workspace_scoped_em_global_nao_espalha_os_itens(conn):
    WorkspaceService().create("Global", scope="global")
    ProjectService().create("global", "Geral")
    WorkspaceService().create("Cliente")
    ProjectService().create("cliente", "app")
    c = _rule("Cliente", "app", "rule/c")
    out = WorkspaceService().merge("Cliente", "Global")
    assert out["scope_changes"] == {"items": 1}
    assert (_record(c).scope, _effective(c)) == ("scoped", "scoped")


def test_mesclar_project_materializa_o_scope_anterior(conn):
    WorkspaceService().create("W")
    ProjectService().create("w", "Velho", scope="global")
    ProjectService().create("w", "Novo")
    a = _rule("W", "Velho", "rule/a")
    out = ProjectService().merge("w", "velho", "novo")
    assert out["scope_changes"] == {"items": 1}
    assert (_record(a).project, _record(a).scope) == ("Novo", "global")


# ============================================================ menores


def test_busca_vazia_com_cara_de_segredo_nao_e_registrada(conn):
    local_state.log_empty_search("teste", "token ghp_" + "a" * 36)
    local_state.log_empty_search("teste", "x" * 500)
    rows = local_state.empty_searches("teste")
    assert [len(r["query"]) for r in rows] == [200]
