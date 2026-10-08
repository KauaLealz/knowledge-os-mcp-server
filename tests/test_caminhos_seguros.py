"""Nada é gravado ou apagado fora da pasta da conexão, venha a key/id do agente ou de um arquivo.

Cenário do ataque: key com `..` (saída de LLM no item_save, ou arquivo publicado no remote) vira
path `{ws}/{pj}/{key}.md`; o id vira `_sem-key/{id}.md` e `.secrets/{id}.enc`.
"""

from datetime import datetime
from pathlib import Path

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.schemas.item_schemas import ItemCreate
from knowledge_os.services.brain import Brain
from knowledge_os.services.git_repo_service import GitRepoService
from knowledge_os.services.item_file import item_path, parse_item_file
from knowledge_os.services.item_service import ItemService
from knowledge_os.storage.files import FileStore, ItemRecord

KEYS_RUINS = [
    "a/../../x",
    "a/../../../../../.claude/CLAUDE",
    "a//b",
    "a/./b",
    "a/",
    "a/.oculto",
]
IDS_RUINS = ["../../x", "a/b", "a b", "..", "a\\b", "x.y"]


def _frontmatter(key: str | None = "regra/x", id_: str = "id-1", **extra: str) -> str:
    linhas = [f"key: {key}" if key else None, f"id: {id_!r}", "workspace: Polara",
              "project: app", "type: rule", "title: T", "status: active",
              "memory_class: longterm", "created_at: '2026-01-01T00:00:00Z'",
              "updated_at: '2026-01-01T00:00:00Z'", "summary: s"]
    linhas += [f"{k}: {v}" for k, v in extra.items()]
    return "---\n" + "\n".join(x for x in linhas if x) + "\n---\ncorpo\n"


def _rec(**over) -> ItemRecord:
    base = dict(
        id="id-1", key="regra/x", workspace="Polara", project="App", subject=None,
        type="rule", subtype=None, scope=None, title="T", status="active", tags=[], links=[],
        scope_paths=[], ttl_days=None, keywords=None, source=None, origin="agent",
        verified_at=None, verified_commit=None,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        relations=[], summary="s", content="c\n",
    )
    base.update(over)
    return ItemRecord(**base)


# ---- schema e parse -----------------------------------------------------------------------


@pytest.mark.parametrize("key", KEYS_RUINS)
def test_schema_recusa_key_com_segmento_vazio_ponto_ou_oculto(key):
    with pytest.raises(ValueError):
        ItemCreate(workspace_id="w", project_id="p", type="rule", title="t", summary="s",
                   content="c", key=key)


@pytest.mark.parametrize("key", ["regra/money", "v1.2/x_y-z", "a"])
def test_schema_aceita_key_normal(key):
    assert ItemCreate(workspace_id="w", project_id="p", type="rule", title="t", summary="s",
                      content="c", key=key).key == key


@pytest.mark.parametrize("key", [*KEYS_RUINS, "../x", "/abs/x", "C:/x"])
def test_parse_recusa_key_insegura(key):
    with pytest.raises(ValidationError, match="key"):
        parse_item_file(_frontmatter(key=f"'{key}'"))


@pytest.mark.parametrize("id_", IDS_RUINS)
def test_parse_recusa_id_fora_de_letras_numeros_e_hifen(id_):
    with pytest.raises(ValidationError, match="id"):
        parse_item_file(_frontmatter(id_=id_))


@pytest.mark.parametrize("ws", ["..", ".oculto", "!!!"])
def test_parse_recusa_workspace_que_vira_pasta_insegura(ws):
    raw = _frontmatter().replace("workspace: Polara", f"workspace: '{ws}'")
    with pytest.raises(ValidationError, match="workspace"):
        parse_item_file(raw)


@pytest.mark.parametrize("key", ["a/../../x", "a//b"])
def test_item_path_recusa_key_insegura(key):
    with pytest.raises(ValidationError):
        item_path("Polara", "app", key, "id-1")


@pytest.mark.parametrize("id_", ["../../x", "a/b"])
def test_item_path_recusa_id_inseguro(id_):
    with pytest.raises(ValidationError):
        item_path("Polara", "app", None, id_)


# ---- item_save (saída de LLM) -------------------------------------------------------------


def test_item_save_com_key_maliciosa_recusa_e_nao_grava_fora(conn, tmp_path):
    alvo = tmp_path / "fora.md"
    with pytest.raises(ValidationError, match="key"):
        ItemService().save([{"workspace": "Polara", "project": "app", "type": "rule",
                             "key": "a/../../../fora", "title": "t", "summary": "s",
                             "content": "c"}])
    assert not alvo.exists()
    assert not any(p.name == "fora.md" for p in tmp_path.rglob("fora.md"))


# ---- arquivo malicioso no disco (vindo do remote) -----------------------------------------


def test_arquivo_com_key_maliciosa_vai_para_errors_e_nao_e_regravado_fora(conn, tmp_path):
    root = conn.clone_path()
    ItemService().save([{"workspace": "Polara", "project": "app", "type": "rule",
                         "key": "regra/alvo", "title": "Alvo", "summary": "s",
                         "content": "c"}])
    ruim = root / "polara" / "app" / "ruim.md"
    ruim.write_text(_frontmatter(key="'a/../../../../fora'", id_="id-ruim",
                                 relations="[{type: related_to, target: regra/alvo}]"),
                    encoding="utf-8")
    brain = Brain()
    assert brain.snapshot.get("id-ruim") is None
    assert "polara/app/ruim.md" in brain.store.errors
    # Outra escrita (regrava as relações de todos) não toca no arquivo ruim nem grava fora.
    ItemService().save([{"workspace": "Polara", "project": "app", "type": "rule",
                         "key": "regra/outra", "title": "Outra", "summary": "s",
                         "content": "c"}])
    assert not any(tmp_path.rglob("fora.md"))


def test_arquivo_com_id_malicioso_vai_para_errors(tmp_path):
    root = tmp_path / "dados"
    (root / "polara" / "app").mkdir(parents=True)
    (root / "polara" / "app" / "x.md").write_text(
        _frontmatter(id_="../../../segredo"), encoding="utf-8")
    store = FileStore(root)
    assert store.items() == []
    assert "polara/app/x.md" in store.errors


# ---- última barreira: a gravação confere que o destino está dentro da raiz ----------------


def test_write_files_recusa_path_fora_da_pasta(tmp_path):
    clone = tmp_path / "clone"
    git = GitRepoService(clone)
    git.ensure_clone()
    for rel in ("../fora.md", "a/../../fora.md", str(tmp_path / "abs.md")):
        with pytest.raises(ValidationError):
            git.publish({rel: "x"}, "tentativa")
        with pytest.raises(ValidationError):
            git.publish({rel: None}, "tentativa")
    assert not (tmp_path / "fora.md").exists()
    assert not (tmp_path / "abs.md").exists()


def test_write_files_recusa_symlink_para_fora(tmp_path):
    clone = tmp_path / "clone"
    git = GitRepoService(clone)
    git.ensure_clone()
    fora = tmp_path / "fora"
    fora.mkdir()
    try:
        (clone / "link").symlink_to(fora, target_is_directory=True)
    except OSError:
        pytest.skip("sem permissão para criar symlink nesta máquina")
    with pytest.raises(ValidationError):
        git.publish({"link/x.md": "x"}, "tentativa")
    assert not (fora / "x.md").exists()


def test_filestore_write_recusa_destino_fora_da_raiz(tmp_path, monkeypatch):
    import knowledge_os.storage.files as files_mod

    store = FileStore(tmp_path / "dados")
    monkeypatch.setattr(files_mod, "record_text", lambda _r: ("../fora.md", "x"))
    with pytest.raises(ValidationError):
        store.write(_rec())
    assert not (tmp_path / "fora.md").exists()


@pytest.mark.parametrize("id_", ["../../x", "a/b", "..", "a\\b"])
def test_secret_path_recusa_id_inseguro(conn, id_):
    with pytest.raises(ValidationError):
        Brain().secret_path(id_)


def test_secret_path_normal_fica_dentro_de_secrets(conn):
    path = Brain().secret_path("8f3e2c0a-0000-0000-0000-000000000001")
    assert path.parent.name == ".secrets"
    assert Path(path).resolve().is_relative_to(conn.clone_path().resolve())
