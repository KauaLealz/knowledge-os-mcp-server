"""Subcomando `knowledge-mcp ui`: bind local, sem login, URL limpa."""

import os
import re
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import src.main as main_mod

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"^http://127\.0\.0\.1:(\d+)/ui/$", re.M)


@pytest.fixture
def fake_uvicorn(monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setattr(main_mod, "ensure_home", lambda: None)
    monkeypatch.setattr(main_mod, "validate_and_init_config", lambda: None)
    return calls


def _run_ui(capsys, *extra):
    assert main_mod.main(["ui", "--port", "8123", "--no-browser", *extra]) == 0
    return capsys.readouterr().out


def test_ui_escuta_so_em_loopback_e_imprime_url_sem_token(fake_uvicorn, capsys):
    out = _run_ui(capsys)
    m = URL_RE.search(out)
    assert m and m.group(1) == "8123"
    assert "token" not in out.lower()
    assert fake_uvicorn[0]["host"] == "127.0.0.1" and fake_uvicorn[0]["port"] == 8123


def test_ui_abre_o_navegador_a_menos_que_no_browser(fake_uvicorn, capsys, monkeypatch):
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    _run_ui(capsys)
    assert opened == []
    assert main_mod.main(["ui", "--port", "8123"]) == 0
    assert opened == ["http://127.0.0.1:8123/ui/"]


def test_sem_subcomando_continua_sendo_o_stdio():
    assert main_mod._parse_args([]).command is None
    assert main_mod._parse_args(["ui"]).command == "ui"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _status(url, method="GET", origin=None):
    req = urllib.request.Request(url, method=method, data=b"{}" if method != "GET" else None)
    if origin:
        req.add_header("Origin", origin)
    req.add_header("Content-Type", "application/json")
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_ui_de_verdade_responde_sem_token_e_recusa_escrita_de_outra_origem(tmp_path):
    port = _free_port()
    env = {**os.environ, "KNOWLEDGE_OS_HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT)}
    env.pop("MCP_DB_PATH", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.main", "ui", "--port", str(port), "--no-browser"],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    watchdog = threading.Timer(60, proc.kill)  # readline não trava a suíte se o servidor falhar
    watchdog.start()
    try:
        assert URL_RE.search(proc.stdout.readline()), "URL não impressa"
        base = f"http://127.0.0.1:{port}"
        assert _status(f"{base}/api/workspaces") == 200
        assert _status(f"{base}/api/workspaces", "POST", origin="http://evil.test") == 403
    finally:
        watchdog.cancel()
        proc.terminate()
        proc.wait(timeout=10)
        proc.stdout.close()


def test_ui_porta_ocupada_falha_antes_de_imprimir_a_url(fake_uvicorn, capsys):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert main_mod.main(["ui", "--port", str(port), "--no-browser"]) == 1
    captured = capsys.readouterr()
    assert "/ui/" not in captured.out
    assert str(port) in captured.err and "ocupada" in captured.err
    assert fake_uvicorn == []
