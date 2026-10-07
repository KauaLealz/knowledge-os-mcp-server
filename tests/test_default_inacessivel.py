"""Default do connections.json inacessível não impede o MCP/UI de subir."""

import asyncio
import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import knowledge_os.main as main_mod
from tests.helpers_multidb import catalog  # noqa: F401  (fixture reaproveitada)
from tests.test_stdio import server_env  # noqa: F401  (fixture reaproveitada)


def _write_down_default(home):
    """`default` aponta para uma conexão com `review_mode` inválido: connections.json
    não carrega (ConfigError), sem envolver rede — o servidor ainda precisa subir."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "connections.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "default": "pg",
                "connections": [
                    {"id": "pg", "name": "PG", "review_mode": "sync"},
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def down_default(monkeypatch, catalog):  # noqa: F811
    import knowledge_os.config as config

    _write_down_default(config.KNOWLEDGE_HOME)
    monkeypatch.setattr(main_mod, "ensure_home", lambda: None)
    return config.KNOWLEDGE_HOME


def test_bootstrap_sobe_com_default_inacessivel(down_default, capsys):
    assert main_mod.main(["--bootstrap"]) == 0
    assert "bootstrap: OK" in capsys.readouterr().out


def test_ui_sobe_com_default_inacessivel(down_default, monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn.Server, "run",
                        lambda self, sockets=None: calls.append(sockets[0].close()))
    assert main_mod.main(["ui", "--port", "8123", "--no-browser"]) == 0
    assert calls


def test_stdio_sobe_e_tool_sem_connection_id_da_erro_explicito(server_env):  # noqa: F811
    cwd, env, home = server_env
    _write_down_default(home)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "knowledge_os.main"], env=env, cwd=str(cwd)
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                broken = await session.call_tool("workspace", {"action": "list"})
                cat = await session.call_tool(
                    "workspace", {"action": "list", "connection_id": "default"})
                return broken, cat

    broken, cat = asyncio.run(asyncio.wait_for(scenario(), timeout=60))
    assert broken.is_error
    assert "pg" in broken.content[0].text
    assert not cat.is_error
