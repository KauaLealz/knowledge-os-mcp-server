"""Pytest fixtures compartilhadas para testes."""

import os
import tempfile

# Home de dados da suíte: definido antes de qualquer import de `knowledge_os`, para que as
# constantes lidas no import nunca apontem para o ~/.knowledge-os real.
os.environ["KNOWLEDGE_OS_HOME"] = tempfile.mkdtemp(prefix="kos-test-home-")

import pytest  # noqa: E402

import knowledge_os.config as config  # noqa: E402
from knowledge_os.config import ConfigManager, ConnectionConfig, ConnectionsFile  # noqa: E402
from knowledge_os.services.brain import Project, Workspace  # noqa: E402
from knowledge_os.services.project_service import ProjectService  # noqa: E402
from knowledge_os.services.workspace_service import WorkspaceService  # noqa: E402

config.ensure_home()


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Cada teste tem o seu home: connections.json, repos.json e uso vivem em tmp_path."""
    home = tmp_path / "home"
    monkeypatch.setattr(config, "KNOWLEDGE_HOME", home)
    monkeypatch.setattr(config, "REPOS_DIR", home / "repos")
    monkeypatch.setattr(ConfigManager, "CONNECTIONS_FILE", home / "connections.json")
    # Chave mestra dos segredos por variável: teste nunca toca o keyring da máquina.
    monkeypatch.setenv("KNOWLEDGE_OS_VAULT_KEY", "dGVzdGUtdGVzdGUtdGVzdGUtdGVzdGUtdGVzdGUtMTI=")
    return home


def make_connection(folder, conn_id: str = "teste", name: str = "Teste",
                    default: bool = True, **extra) -> ConnectionConfig:
    """Grava (acrescenta) uma conexão sobre `folder` no connections.json do home do teste."""
    folder.mkdir(parents=True, exist_ok=True)
    conn = ConnectionConfig(id=conn_id, name=name, path=str(folder), **extra)
    current = ConfigManager.load()
    connections = [c for c in current.connections if c.id != conn_id] + [conn]
    ConfigManager.save(ConnectionsFile(
        default=conn_id if default or current.default is None else current.default,
        connections=connections,
    ))
    return conn


@pytest.fixture
def conn(tmp_path) -> ConnectionConfig:
    """Conexão padrão sobre uma pasta temporária (vira repositório git na primeira escrita)."""
    return make_connection(tmp_path / "dados")


@pytest.fixture
def data_dir(conn):
    """Pasta da conexão padrão dos testes."""
    return conn.clone_path()


@pytest.fixture
def sample_workspace(conn) -> Workspace:
    return WorkspaceService().create("TestWorkspace", "Workspace para testes")


@pytest.fixture
def sample_project(sample_workspace: Workspace) -> Project:
    return ProjectService().create(sample_workspace.id, "TestProject", "Project para testes")

