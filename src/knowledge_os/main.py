"""MCP Knowledge OS - Servidor Principal."""

import argparse
import logging
import os
import socket
import sys
import threading
from pathlib import Path

if __name__ == "__main__":
    # `python src/knowledge_os/main.py` põe o pacote em sys.path[0], o que faria mcp/ sombrear o
    # pacote `mcp` real. Troca por src/.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from fastmcp import FastMCP  # noqa: E402

from knowledge_os.config import (  # noqa: E402
    LOG_LEVEL,
    UI_DEFAULT_PORT,
    ConfigManager,
    ensure_home,
    validate_config,
)
from knowledge_os.exceptions import ConfigError, StorageError  # noqa: E402

logger = logging.getLogger(__name__)

_MCP_DIR = Path(__file__).resolve().parent / "mcp"
INSTRUCTIONS_FILE = _MCP_DIR / "INSTRUCTIONS.md"

# Inicializar FastMCP (as instructions chegam ao agente no handshake do protocolo e entram
# no contexto de toda sessão). O arquivo é gerado por `mcp/instructions.py`.
mcp = FastMCP(name="knowledge-mcp", instructions=INSTRUCTIONS_FILE.read_text(encoding="utf-8"))


def register_all_tools() -> None:
    """Registra as 32 ferramentas de `mcp/tools.py` (inclusive `health_check`)."""
    from knowledge_os.mcp import tools

    tools.register(mcp)


def report_connections() -> None:
    """Lê o connections.json do home e testa as conexões ativas (nada é criado).

    Escreve em stderr: o stdout é o canal do protocolo MCP.
    """
    config = ConfigManager.load()
    if not config.connections:
        print("Nenhuma conexão configurada (connection_create cria uma).", file=sys.stderr)
    print(f"Loaded: {ConfigManager.CONNECTIONS_FILE}", file=sys.stderr)
    for conn in config.connections:
        if not conn.enabled:
            continue
        result = ConfigManager.validate_connection(conn)
        if result["status"] == "ok":
            print(f"Connected: {conn.name} ({conn.id})", file=sys.stderr)
        else:
            print(f"Failed: {conn.name} ({conn.id}) - {result['message']}", file=sys.stderr)


def _report_connections_safely() -> None:
    """report_connections para rodar em thread: erro vira linha no stderr, nunca exceção."""
    try:
        report_connections()
    except Exception as exc:  # noqa: BLE001 - diagnóstico não pode derrubar o servidor
        print(f"Diagnóstico de conexões falhou: {exc}", file=sys.stderr)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="knowledge-mcp", description="MCP Knowledge OS")
    sub = parser.add_subparsers(dest="command")
    ui = sub.add_parser("ui", help="sobe a UI web local (somente 127.0.0.1)")
    ui.add_argument("--port", type=int, default=UI_DEFAULT_PORT, help="porta (padrão: 8765)")
    ui.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    return parser.parse_args(argv)


def _bind_ui_socket(port: int) -> socket.socket | None:
    """Reserva a porta em 127.0.0.1 com uso exclusivo; ocupada → None.

    No POSIX, SO_REUSEADDR só permite rebindar uma porta presa em TIME_WAIT (todo fechamento
    de conexão aceita deixa isso por ~60s) — não deixa dois processos escutando a mesma porta
    ao mesmo tempo (isso exigiria SO_REUSEPORT, que não ligamos). Sem isso, qualquer requisição
    HTTP real feita à UI trava o próximo bind por até um minuto, mesmo sem ninguém mais
    escutando na porta — era a causa do servidor "não ficar de pé sempre".

    Exclusivo de verdade no Windows: o SO_REUSEADDR que o uvicorn liga deixaria duas instâncias
    na mesma porta, cada requisição caindo numa — por isso SO_EXCLUSIVEADDRUSE ali, não
    SO_REUSEADDR (que no Windows tem semântica de permitir o compartilhamento).
    """
    sock = socket.socket()
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        return None
    return sock


def ui_enabled() -> bool:
    """A UI sobe junto com o MCP, a menos que KNOWLEDGE_OS_UI=0."""
    return os.environ.get("KNOWLEDGE_OS_UI", "1").strip().lower() not in ("0", "false", "no")


class BackgroundUI:
    """UI dentro do processo MCP, numa thread: nada no stdout (é o canal do protocolo).

    Com dois clientes (Claude e Cursor), o primeiro serve a porta; o outro espera e assume se
    ela ficar livre.
    """

    def __init__(self, port: int = UI_DEFAULT_PORT, retry_seconds: float = 5.0) -> None:
        self.port = port
        self.retry_seconds = retry_seconds
        self.serving = False
        self._server = None
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="knowledge-os-ui", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.should_exit = True

    def _loop(self) -> None:
        while not self._stop.is_set():
            sock = _bind_ui_socket(self.port)
            if sock is not None:
                self._serve(sock)
            self._stop.wait(self.retry_seconds)

    def _serve(self, sock: socket.socket) -> None:
        try:
            import uvicorn

            from knowledge_os.api.main import app

            config = uvicorn.Config(app, log_config=None, access_log=False, log_level="warning")
            self._server = uvicorn.Server(config)
            self.serving = True
            print(f"UI: http://127.0.0.1:{self.port}/ui/", file=sys.stderr)
            self._server.run(sockets=[sock])
        except BaseException:  # noqa: BLE001 - a UI nunca derruba o MCP (uvicorn sai com SystemExit)
            logger.warning("UI parou", exc_info=True)
        finally:
            self.serving = False
            self._server = None
            sock.close()


_background_ui: BackgroundUI | None = None


@mcp.resource(
    "knowledge-os://ui",
    name="UI local",
    description=(
        "URL da interface web local do knowledge-os e se ela está respondendo agora. A UI "
        "sobe junto com o MCP; com vários clientes abertos, só um serve por vez."
    ),
    mime_type="application/json",
)
def ui_resource() -> dict[str, object]:
    ui = _background_ui
    port = ui.port if ui is not None else UI_DEFAULT_PORT
    return {
        "url": f"http://127.0.0.1:{port}/ui/",
        "serving": bool(ui is not None and ui.serving),
    }


def run_ui(port: int, open_browser: bool) -> None:
    """Sobe a UI/API em 127.0.0.1, sem login. A URL vai ao stdout (não é modo MCP)."""
    import uvicorn

    from knowledge_os.api.main import app

    # Reserva a porta antes de anunciar a URL: porta ocupada = URL de outro processo.
    sock = _bind_ui_socket(port)
    if sock is None:
        raise ConfigError(f"Porta {port} ocupada em 127.0.0.1; use --port")

    url = f"http://127.0.0.1:{port}/ui/"
    print(url, flush=True)
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada principal. Retorna o código de saída."""
    args = _parse_args(argv)
    logging.basicConfig(level=LOG_LEVEL, stream=sys.stderr)
    try:
        ensure_home()
        validate_config()
        if args.command == "ui":
            run_ui(args.port, open_browser=not args.no_browser)
            return 0

        # Diagnóstico das conexões em segundo plano: uma conexão fora do ar não pode
        # atrasar o handshake (o cliente MCP desiste em ~30 s).
        threading.Thread(target=_report_connections_safely, daemon=True).start()
        if ui_enabled():
            global _background_ui
            _background_ui = BackgroundUI()
            _background_ui.start()
        register_all_tools()
        mcp.run()
        return 0
    except KeyboardInterrupt:
        print("Encerrando...", file=sys.stderr)
        return 0
    except (ConfigError, StorageError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
