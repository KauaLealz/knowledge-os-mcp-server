"""Subcomando `knowledge-mcp ui`: bind local, sem login, URL limpa."""

import json
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

import knowledge_os.main as main_mod

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"^http://127\.0\.0\.1:(\d+)/ui/$", re.M)


@pytest.fixture
def fake_uvicorn(monkeypatch):
    import uvicorn

    calls = []

    def fake_run(self, sockets=None):
        host, port = sockets[0].getsockname()[:2]
        sockets[0].close()
        calls.append({"host": host, "port": port})

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    monkeypatch.setattr(main_mod, "ensure_home", lambda: None)
    monkeypatch.setattr(main_mod, "validate_config", lambda: None)
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
    env = {**os.environ, "KNOWLEDGE_OS_HOME": str(tmp_path / "home"),
           "PYTHONPATH": str(ROOT / "src")}
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "connections.json").write_text(json.dumps({
        "version": "1.0", "default": "d",
        "connections": [{"id": "d", "name": "Dados", "path": str(tmp_path / "dados")}],
    }), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "knowledge_os.main", "ui", "--port", str(port), "--no-browser"],
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


def _wait_status(url, timeout=15.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            return urllib.request.urlopen(url, timeout=2).status
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    return None


@pytest.fixture
def background_ui():
    started = []

    def start(port, retry=0.2):
        ui = main_mod.BackgroundUI(port, retry_seconds=retry)
        ui.start()
        started.append(ui)
        return ui

    yield start
    for ui in started:
        ui.stop()


def test_ui_sobe_junto_com_o_mcp_sem_escrever_no_stdout(background_ui, capfd):
    port = _free_port()
    background_ui(port)
    assert _wait_status(f"http://127.0.0.1:{port}/ui/") == 200
    assert capfd.readouterr().out == ""  # stdout é o canal do protocolo MCP


def test_porta_ocupada_reaproveita_e_assume_quando_a_outra_cai(background_ui):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    ui = background_ui(port)
    import time

    time.sleep(0.5)
    assert ui.serving is False  # outra instância (ou outro programa) atende a porta
    busy.close()
    assert _wait_status(f"http://127.0.0.1:{port}/ui/") == 200
    assert ui.serving is True


def test_knowledge_os_ui_0_desliga(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_OS_UI", "0")
    assert main_mod.ui_enabled() is False
    monkeypatch.delenv("KNOWLEDGE_OS_UI")
    assert main_mod.ui_enabled() is True


def test_bind_rebinda_logo_apos_conexao_aceita_e_fechada():
    """Sem SO_REUSEADDR, uma porta com conexão aceita (qualquer requisição HTTP real) fica em
    TIME_WAIT por até ~60s depois do socket fechar — o processo seguinte não consegue reocupar
    a porta mesmo sem ninguém mais escutando nela."""
    port = _free_port()
    sock = main_mod._bind_ui_socket(port)
    assert sock is not None
    sock.listen(1)
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = sock.accept()
    conn.close()
    sock.close()
    client.close()

    sock2 = main_mod._bind_ui_socket(port)
    assert sock2 is not None, "porta deveria rebindar logo após fechar, sem esperar TIME_WAIT"
    sock2.close()
