"""Em `review_mode="pr"` nada local muda antes do merge: nem `.secrets/*.enc`, nem `repos.json`.

Remover/renomear/mesclar workspace ou project só abre um PR; o valor cifrado dos segredos e as
ligações de repositório só mudam quando a publicação for direta ("published").
"""

import subprocess
from unittest.mock import patch

import pytest

from knowledge_os.config import ConfigManager
from knowledge_os.services import gh_cli
from knowledge_os.services.brain import Brain
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.repo_service import RepoService
from knowledge_os.services.secret_service import SecretService
from knowledge_os.services.workspace_service import WorkspaceService
from knowledge_os.storage import local_state

VALUE = "npm_Zx81kQ2pL0aVb7Yt3Rw9Mn4C"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def bare_repo(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "_seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True)
    _git(seed, "config", "user.email", "seed@local")
    _git(seed, "config", "user.name", "seed")
    (seed / "README.md").write_text("inicial\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-q", "-m", "inicial")
    _git(seed, "push", "-q", "origin", "main")
    return bare


@pytest.fixture
def pr_conn(bare_repo, tmp_path):
    """Conexão com remote: itens, segredo com valor e repo ligado em modo direto; depois PR."""
    conn = ConnectionService().create("ComPR", str(tmp_path / "ComPR"), remote_url=str(bare_repo),
                                      review_mode="direct", test=False)
    cid = conn.id
    ItemService(connection_id=cid).save([
        {"workspace": "Org", "project": "app", "key": "regra/x", "type": "rule",
         "title": "Regra", "summary": "s", "content": "c"},
        {"workspace": "Org", "project": "outro", "key": "regra/y", "type": "rule",
         "title": "Outra", "summary": "s", "content": "c"},
    ])
    RepoService(connection_id=cid).link("github.com/org/app", "Org", "app")
    secret_id = ItemService(connection_id=cid).save([
        {"workspace": "Org", "project": "app", "key": "segredo/npm", "type": "secret",
         "title": "Token", "summary": "npm"},
    ])[0]["id"]
    SecretService(connection_id=cid).set_value(secret_id, VALUE)
    config = ConfigManager.load()
    config.get_connection(cid).review_mode = "pr"
    ConfigManager.save(config)
    brain = Brain(cid)
    return {"cid": cid, "secret": brain.secret_path(secret_id),
            "link": dict(local_state.get_repo("github.com/org/app") or {})}


@pytest.fixture
def gh_mock():
    with (
        patch.object(gh_cli, "has_push_access", return_value=None),
        patch.object(gh_cli, "pr_create", return_value="https://example.invalid/pr/1") as pr,
    ):
        yield pr


def _intacto(ctx):
    assert ctx["secret"].is_file(), "o .enc não pode sumir antes do merge"
    assert local_state.get_repo("github.com/org/app") == ctx["link"]


def test_workspace_delete_em_pr_mantem_enc_e_ligacao(pr_conn, gh_mock):
    assert WorkspaceService(pr_conn["cid"]).delete("Org") is True
    gh_mock.assert_called_once()
    _intacto(pr_conn)


def test_workspace_rename_em_pr_nao_mexe_na_ligacao(pr_conn, gh_mock):
    WorkspaceService(pr_conn["cid"]).update("Org", new_name="Nova")
    gh_mock.assert_called_once()
    _intacto(pr_conn)


def test_workspace_update_em_pr_nao_mexe_na_ligacao(pr_conn, gh_mock):
    WorkspaceService(pr_conn["cid"]).update("Org", "Nova")
    _intacto(pr_conn)


def test_workspace_merge_em_pr_nao_mexe_na_ligacao(pr_conn, gh_mock, tmp_path):
    cid = pr_conn["cid"]
    config = ConfigManager.load()
    config.get_connection(cid).review_mode = "direct"
    ConfigManager.save(config)
    WorkspaceService(cid).create("Destino")
    config.get_connection(cid).review_mode = "pr"
    ConfigManager.save(config)
    WorkspaceService(cid).merge("Org", "Destino")
    _intacto(pr_conn)


def test_project_delete_em_pr_mantem_enc_e_ligacao(pr_conn, gh_mock):
    assert ProjectService(pr_conn["cid"]).delete("org", "app") is True
    gh_mock.assert_called_once()
    _intacto(pr_conn)


def test_project_update_em_pr_nao_mexe_na_ligacao(pr_conn, gh_mock):
    ProjectService(pr_conn["cid"]).update("org", "app", "app2")
    _intacto(pr_conn)


def test_project_merge_em_pr_nao_mexe_na_ligacao(pr_conn, gh_mock):
    ProjectService(pr_conn["cid"]).merge("org", "app", "outro")
    _intacto(pr_conn)


def test_project_delete_direto_apaga_enc_e_ligacao(pr_conn):
    cid = pr_conn["cid"]
    config = ConfigManager.load()
    config.get_connection(cid).review_mode = "direct"
    ConfigManager.save(config)
    assert ProjectService(cid).delete("org", "app") is True
    assert not pr_conn["secret"].exists()
    assert local_state.get_repo("github.com/org/app") is None
