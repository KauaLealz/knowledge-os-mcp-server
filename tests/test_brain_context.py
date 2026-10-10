"""Ligação de repositórios ao segundo cérebro (o pacote de contexto está em test_pack.py)."""

import subprocess

import pytest

from knowledge_os.services.context_service import ContextService
from knowledge_os.services.repo_service import RepoService, normalize_remote, repo_key


@pytest.mark.parametrize("remote", [
    "git@github.com:KauaLealz/projpro.git",
    "https://github.com/KauaLealz/projpro",
    "https://token@github.com/kaualealz/projpro.git/",
    "ssh://git@github.com/KauaLealz/projpro.git",
])
def test_remote_normalizado(remote):
    assert normalize_remote(remote) == "github.com/kaualealz/projpro"


def test_chave_de_pasta_com_e_sem_remote(tmp_path):
    repo = tmp_path / "Repo"
    (repo / "src" / "deep").mkdir(parents=True)
    if subprocess.run(["git", "init", "-q", str(repo)], capture_output=True).returncode:
        pytest.skip("git init falhou na pasta temporária (ambiente sem permissão de escrita)")
    assert repo_key(str(repo / "src" / "deep")) == "path:" + repo.resolve().as_posix().lower()
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "git@github.com:Org/Repo.git"], check=True)
    assert repo_key(str(repo)) == "github.com/org/repo"


def test_projeto_nao_ligado_explica_como_ligar(conn):
    out = ContextService().build("github.com/org/outro")
    assert out["linked"] is False and "/plumb-setup" in out["markdown"]


def test_link_e_resolve(conn):
    RepoService().link("git@github.com:Org/App.git", "Polara", "app")
    found = RepoService().resolve("https://github.com/org/app")
    assert (found["workspace"], found["project"]) == ("Polara", "app")


def test_link_sem_workspace_usa_o_dono_e_o_repo(conn):
    out = RepoService().link("git@github.com:Polara-Innovations/projpro.git")
    assert (out["workspace"], out["project"]) == ("polara-innovations", "projpro")
    out = RepoService().link("path:c:/projects/meu-app")
    assert (out["workspace"], out["project"]) == ("Pessoal", "meu-app")


def test_segundo_repo_do_mesmo_dono_cai_no_mesmo_workspace(conn):
    RepoService().link("github.com/polara-innovations/projpro", "Polara")
    out = RepoService().link("github.com/polara-innovations/synapse")
    assert (out["workspace"], out["project"]) == ("Polara", "synapse")
    outro = RepoService().link("github.com/kaualealz/plumb-harness")
    assert outro["workspace"] == "kaualealz"  # outro dono: não herda
