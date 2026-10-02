"""Subcomando `knowledge-mcp ui`: bind local, token por start e URL com fragmento."""

import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import src.main as main_mod
from src.api import auth as auth_mod

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/ui/#token=([A-Za-z0-9_-]+)")


@pytest.fixture
def fake_uvicorn(monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setattr(main_mod, "ensure_home", lambda: None)
    monkeypatch.setattr(main_mod, "validate_and_init_config", lambda: None)
    yield calls
    auth_mod.set_token(None)


def _run_ui(capsys, *extra):
    assert main_mod.main(["ui", "--port", "8123", "--no-browser", *extra]) == 0
    return URL_RE.search(capsys.readouterr().out)


def test_ui_escuta_so_em_loopback_e_imprime_url_com_token(fake_uvicorn, capsys):
    m = _run_ui(capsys)
    assert m and m.group(1) == "8123" and len(m.group(2)) >= 32
    assert fake_uvicorn[0]["host"] == "127.0.0.1" and fake_uvicorn[0]["port"] == 8123
    assert auth_mod._token == m.group(2)


def test_token_novo_a_cada_start(fake_uvicorn, capsys):
    t1 = _run_ui(capsys).group(2)
    t2 = _run_ui(capsys).group(2)
    assert t1 != t2 and auth_mod._token == t2


def test_ui_abre_o_navegador_a_menos_que_no_browser(fake_uvicorn, capsys, monkeypatch):
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    _run_ui(capsys)
    assert opened == []
    assert main_mod.main(["ui", "--port", "8123"]) == 0
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:8123/ui/#token=")


def test_sem_subcomando_continua_sendo_o_stdio():
    assert main_mod._parse_args([]).command is None
    assert main_mod._parse_args(["ui"]).command == "ui"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_ui_de_verdade_responde_401_sem_token_e_200_com_o_certo(tmp_path):
    port = _free_port()
    env = {**os.environ, "KNOWLEDGE_OS_HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT)}
    env.pop("MCP_DB_PATH", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.main", "ui", "--port", str(port), "--no-browser"],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        m = URL_RE.search(proc.stdout.readline())
        assert m, "URL não impressa"
        token = m.group(2)
        base = f"http://127.0.0.1:{port}"
        assert _get(f"{base}/api/workspaces") == 401
        assert _get(f"{base}/api/workspaces", "errado") == 401
        assert _get(f"{base}/api/workspaces", token) == 200
    finally:
        proc.terminate()
        proc.wait(timeout=10)
