"""`cli._sync_connection`: puxa o repositório git da connection ativa antes do contexto
(GS-L4, ponto 4). Em processo (não subprocess): mais rápido e testa `_context` tolerando
falha diretamente."""

import subprocess
from pathlib import Path

import pytest

from knowledge_os import cli
from knowledge_os.config import ConfigManager
from knowledge_os.services.connection_service import ConnectionService


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def _set_default(connection_id: str) -> None:
    config = ConfigManager.load()
    config.default = connection_id
    ConfigManager.save(config)


def test_sem_connection_nao_faz_nada(tmp_path):
    cli._sync_connection()  # sem conexão: no-op, não levanta


def test_puxa_mudanca_da_connection_default(bare_repo, tmp_path):
    dest = tmp_path / "sync-dest"
    conn = ConnectionService().create(
        "Sync", str(dest), remote_url=str(bare_repo), review_mode="direct", test=False
    )
    _set_default(conn.id)
    clone_path = ConfigManager.load().get_connection(conn.id).clone_path()

    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(bare_repo), str(other))
    _git(other, "config", "user.email", "o@local")
    _git(other, "config", "user.name", "o")
    (other / "novo.txt").write_text("x", encoding="utf-8")
    _git(other, "add", "novo.txt")
    _git(other, "commit", "-q", "-m", "novo")
    _git(other, "push", "-q", "origin", "main")

    assert not (clone_path / "novo.txt").exists()
    cli._sync_connection()
    assert (clone_path / "novo.txt").exists()


def test_falha_de_rede_nao_quebra_o_hook(bare_repo, tmp_path, monkeypatch):
    """Connection cujo remote some depois de clonada (rede fora): `_context` segue sem
    sincronizar (tolerância a erro), igual ao resto do hook."""
    import argparse

    dest = tmp_path / "semrede-dest"
    conn = ConnectionService().create(
        "SemRede",
        str(dest),
        remote_url=str(bare_repo),
        review_mode="direct",
        test=False,
    )
    _set_default(conn.id)

    # remote passa a apontar para algo inalcançável (rede caiu depois do clone inicial)
    config = ConfigManager.load()
    config.get_connection(conn.id).remote_url = "https://example.invalid/nao-existe.git"
    ConfigManager.save(config)

    args = argparse.Namespace(hook=None, repo=str(tmp_path), paths=[], query=None, budget=500)
    code = cli._context(args)
    assert code == 0  # não propaga a falha de rede
