"""O `sync` (git pull) da conexão roda com as duas travas das escritas: a do processo
(`lock_for`) e a entre processos (`folder_lock`) — senão um pull no meio de um publish de
outro cliente bagunça a cópia de trabalho."""

from contextlib import contextmanager

import pytest

from knowledge_os import cli
from knowledge_os.mcp.tools import repo as repo_tool
from knowledge_os.services.git_repo_service import GitRepoService
from knowledge_os.storage import access


@pytest.fixture
def espiao(monkeypatch):
    """Registra se as travas estavam presas quando o sync rodou."""
    estado = {"pasta": 0, "sync": []}
    original = access.folder_lock

    @contextmanager
    def trava(root, *a, **k):
        with original(root, *a, **k):
            estado["pasta"] += 1
            try:
                yield
            finally:
                estado["pasta"] -= 1

    def sync(self):
        lock = access.lock_for(estado["cid"])
        # RLock: `_is_owned` diz se esta thread a segura.
        estado["sync"].append((estado["pasta"] > 0, lock._is_owned()))
        return False

    monkeypatch.setattr(access, "folder_lock", trava)
    monkeypatch.setattr(GitRepoService, "sync", sync)
    return estado


def test_repo_sync_usa_as_duas_travas(conn, espiao):
    espiao["cid"] = conn.id
    assert repo_tool(action="sync") == {"synced": False}
    assert espiao["sync"] == [(True, True)]


def test_sync_do_hook_usa_as_duas_travas(conn, espiao):
    espiao["cid"] = conn.id
    cli._sync_connection()
    assert espiao["sync"] == [(True, True)]
