"""Servidor MCP real por stdio (subprocess) e empacotamento do wheel."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TOOLS = 40


@pytest.fixture
def server_env(tmp_path):
    """cwd e home temporários, separados: nada deve ser criado no cwd."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "MCP_DB_PATH"}
    env.update(
        KNOWLEDGE_OS_HOME=str(tmp_path / "home"),
        PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        LOG_LEVEL="WARNING",
    )
    return cwd, env, tmp_path / "home"


def test_handshake_stdio_initialize_list_tools_health_check(server_env):
    cwd, env, home = server_env
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.main"], env=env, cwd=str(cwd)
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                health = await session.call_tool("health_check", {})
                return init, tools, health

    init, tools, health = asyncio.run(asyncio.wait_for(scenario(), timeout=60))
    assert init.serverInfo.name == "knowledge-mcp"
    assert len(tools.tools) == EXPECTED_TOOLS
    assert not health.is_error
    assert json.loads(health.content[0].text) == {"status": "ok", "database": "connected"}
    assert list(cwd.iterdir()) == []  # nada criado no cwd
    assert {p.name for p in home.iterdir()} >= {"connections.json", "knowledge.db"}


def test_stdout_so_tem_protocolo(server_env):
    cwd, env, _ = server_env
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.main"], cwd=cwd, env=env, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        for m in msgs:
            proc.stdin.write(json.dumps(m) + "\n")
            proc.stdin.flush()
        seen = []
        while not any(r.get("id") == 2 for r in seen):
            line = proc.stdout.readline()
            assert line, "servidor encerrou antes de responder"
            seen.append(json.loads(line))  # qualquer linha fora do JSON falha aqui
    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=10)
    assert all(r.get("jsonrpc") == "2.0" for r in seen)
    assert len(next(r for r in seen if r.get("id") == 2)["result"]["tools"]) == EXPECTED_TOOLS


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv não instalado")
def test_wheel_inclui_instructions_e_static(tmp_path):
    # Constrói a partir de uma cópia: o build não deixa build/ nem egg-info no repo.
    proj = tmp_path / "proj"
    shutil.copytree(ROOT, proj, ignore=shutil.ignore_patterns(
        ".git", ".venv", ".plumb", ".claude", ".tmp*", ".uv*", ".*cache", "build", "dist*",
        "database", "*.egg-info", "__pycache__", ".knowledge"))
    out = tmp_path / "out"
    # Cache e temporários isolados: o build não depende do cache global do uv (que pode
    # estar inacessível, ex.: dentro de apps empacotados no Windows).
    scratch = tmp_path / "uv"
    scratch.mkdir()
    env = dict(os.environ, UV_CACHE_DIR=str(scratch / "cache"), TMP=str(scratch), TEMP=str(scratch))
    subprocess.run(
        ["uv", "build", "--wheel", "-o", str(out), str(proj)],
        check=True, capture_output=True, text=True, timeout=300, env=env,
    )
    (wheel,) = out.glob("knowledge_mcp-*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    assert "src/mcp/INSTRUCTIONS.md" in names
    static = {p.relative_to(ROOT).as_posix() for p in (ROOT / "src/api/static").rglob("*")
              if p.is_file()}
    assert static and static <= names
