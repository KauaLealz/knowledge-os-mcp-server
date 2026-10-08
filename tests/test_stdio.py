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
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TOOLS = 33


@pytest.fixture
def server_env(tmp_path):
    """cwd e home temporários, separados: nada deve ser criado no cwd."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = dict(os.environ)
    env.update(
        KNOWLEDGE_OS_HOME=str(tmp_path / "home"),
        KNOWLEDGE_OS_UI="0",
        PYTHONPATH=str(ROOT / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        LOG_LEVEL="WARNING",
    )
    return cwd, env, tmp_path / "home"


def test_handshake_stdio_initialize_list_tools_health_check(server_env):
    cwd, env, home = server_env
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "knowledge_os.main"], env=env, cwd=str(cwd)
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                health = await session.call_tool("health_check", {})
                return init, tools, health

    init, tools, health = asyncio.run(asyncio.wait_for(scenario(), timeout=60))
    assert init.server_info.name == "knowledge-mcp"
    assert len(tools.tools) == EXPECTED_TOOLS
    assert not health.is_error
    report = json.loads(health.content[0].text)
    # Sem conexão: o servidor sobe, mas diz que falta criar uma (nada é criado sozinho).
    assert (report["status"], report["connection"]) == ("error", None)
    assert "connection_create" in report["message"] and report["version"]
    assert list(cwd.iterdir()) == []  # nada criado no cwd
    assert not (home / "connections.json").exists()


def test_health_check_com_conexao_padrao(server_env, tmp_path):
    cwd, env, home = server_env
    data = tmp_path / "dados"
    subprocess.run(["git", "init", "-q", str(data)], check=True)
    home.mkdir(parents=True)
    (home / "connections.json").write_text(json.dumps({
        "version": "1.0", "default": "d",
        "connections": [{"id": "d", "name": "Dados", "path": str(data)}],
    }), encoding="utf-8")
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "knowledge_os.main"], env=env, cwd=str(cwd)
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool("health_check", {})

    health = asyncio.run(asyncio.wait_for(scenario(), timeout=60))
    report = json.loads(health.content[0].text)
    assert report["status"] == "ok"
    assert report["connection"] == {"id": "d", "name": "Dados", "path": str(data),
                                    "exists": True, "is_git_repo": True}


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
        [sys.executable, "-m", "knowledge_os.main"], cwd=cwd, env=env, text=True, encoding="utf-8",
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
        proc.stdout.close()
    assert all(r.get("jsonrpc") == "2.0" for r in seen)
    assert len(next(r for r in seen if r.get("id") == 2)["result"]["tools"]) == EXPECTED_TOOLS


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv não instalado")
def test_wheel_inclui_instructions_e_static(tmp_path):
    # Constrói a partir de uma cópia: o build não deixa build/ nem egg-info no repo.
    proj = tmp_path / "proj"
    shutil.copytree(ROOT, proj, ignore=shutil.ignore_patterns(
        ".git", ".venv", ".plumb", ".claude", ".tmp*", ".uv*", ".*cache", "build", "dist*",
        "*.egg-info", "__pycache__", ".knowledge"))
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
    assert "knowledge_os/mcp/INSTRUCTIONS.md" in names
    pkg = ROOT / "src" / "knowledge_os"
    static = {"knowledge_os/" + p.relative_to(pkg).as_posix()
              for p in (pkg / "api" / "static").rglob("*") if p.is_file()}
    assert static and static <= names
    assert any(n.startswith("knowledge_os/api/static/vendor/") and n.endswith(".js")
               for n in names)
    # O atalho de instalações antigas não vai no wheel.
    assert not any(n.startswith("src/") or n in {"cli.py", "__init__.py"} for n in names)


def test_atalho_src_cli_de_instalacao_antiga(tmp_path):
    env = dict(os.environ)
    env.update(KNOWLEDGE_OS_HOME=str(tmp_path / "home"), PYTHONPATH=str(ROOT))
    novo = subprocess.run([sys.executable, "-m", "knowledge_os.cli", "--version"],
                          env={**env, "PYTHONPATH": str(ROOT / "src")}, cwd=tmp_path,
                          capture_output=True, text=True, check=True)
    antigo = subprocess.run([sys.executable, "-m", "src.cli", "--version"], env=env,
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert antigo.stdout == novo.stdout and "knowledge-mcp" in novo.stdout
    assert "reinstale" in antigo.stderr and "--force" in antigo.stderr
    assert "reinstale" not in novo.stderr
    # `from src.cli import main` direto (como o entry point antigo) também funciona.
    code = "import sys; sys.path.insert(0, sys.argv[1]); from src.cli import main"
    subprocess.run([sys.executable, "-c", code, str(ROOT)], cwd=tmp_path, env={
        k: v for k, v in env.items() if k != "PYTHONPATH"}, check=True)
