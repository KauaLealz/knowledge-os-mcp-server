"""MCP Knowledge OS - Servidor Principal."""

import argparse
import json
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
from sqlalchemy import inspect, text  # noqa: E402

from knowledge_os.config import (  # noqa: E402
    LOG_LEVEL,
    UI_DEFAULT_PORT,
    ConfigManager,
    ensure_home,
    validate_and_init_config,
    validate_config,
)
from knowledge_os.db.models import Base  # noqa: E402
from knowledge_os.db.session import FTS_TABLE, close_engines, get_engine  # noqa: E402
from knowledge_os.exceptions import ConfigError, DatabaseError  # noqa: E402

logger = logging.getLogger(__name__)

from knowledge_os import __version__  # noqa: E402

_MCP_DIR = Path(__file__).resolve().parent / "mcp"
INSTRUCTIONS_FILE = _MCP_DIR / "INSTRUCTIONS.md"

# Inicializar FastMCP (as instructions chegam ao agente no handshake do protocolo e entram
# no contexto de toda sessão).
mcp = FastMCP(name="knowledge-mcp", instructions=INSTRUCTIONS_FILE.read_text(encoding="utf-8"))


def schema_version() -> str | None:
    """Versão do schema gravada no banco default (None se ainda não sincronizado)."""
    from knowledge_os.db.schema_sync import SCHEMA_META_TABLE

    try:
        with get_engine().connect() as conn:
            return conn.execute(
                text(f"SELECT value FROM {SCHEMA_META_TABLE} WHERE key = 'schema_version'")
            ).scalar()
    except Exception:
        return None


def check_database() -> dict[str, str]:
    """Verifica a conexão com o banco e valida o schema esperado."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text(f"SELECT count(*) FROM {FTS_TABLE}"))
        existing = set(inspect(engine).get_table_names())
    except Exception as exc:
        return {"status": "error", "database": str(exc)}

    missing = sorted((set(Base.metadata.tables) | {FTS_TABLE}) - existing)
    if missing:
        return {"status": "error", "database": f"tabelas ausentes: {', '.join(missing)}"}
    return {"status": "ok", "database": "connected"}


@mcp.tool()
def health_check() -> dict[str, str]:
    """Verifica a saúde do servidor MCP e do banco default.

    **Use quando:** Diagnosticar falhas ou confirmar que o servidor está operacional.
    **Retorna:** {status: ok|error, database: connected | motivo, version, schema_version}.
    **Exemplo:** health_check()
    **Notas:** Valida a conexão e a presença de todas as tabelas (inclusive a de busca textual).
    """
    result = check_database()
    return {**result, "version": __version__, "schema_version": schema_version() or ""}


def register_all_tools() -> None:
    """Registra as 13 ferramentas de `tools.py` (sem conceito de perfil) — `health_check`,
    a 14ª, já está decorada acima, direto neste módulo."""
    from knowledge_os.mcp import tools

    tools.register(mcp)


def report_connections() -> None:
    """Carrega (ou cria) o connections.json do home e testa as conexões ativas.

    Escreve em stderr: o stdout é o canal do protocolo MCP.
    """
    config = ConfigManager.load_or_create()
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


def _run_daily_safely() -> None:
    """Manutenção diária para rodar em thread: erro vira log, nunca exceção."""
    try:
        from knowledge_os.services.maintenance import run_daily

        run_daily()
    except Exception:  # noqa: BLE001 - manutenção não pode derrubar o servidor
        logger.warning("Manutenção diária falhou", exc_info=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="knowledge-mcp", description="MCP Knowledge OS")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check-db", action="store_true", help="verifica conexão e schema do banco e sai"
    )
    group.add_argument(
        "--bootstrap", action="store_true", help="cria schema e labels padrão e sai"
    )
    group.add_argument(
        "--migrate-v2", action="store_true",
        help="migra um banco do schema antigo (domains/project_links) pro novo e sai",
    )
    sub = parser.add_subparsers(dest="command")
    ui = sub.add_parser("ui", help="sobe a UI web local (somente 127.0.0.1)")
    ui.add_argument("--port", type=int, default=UI_DEFAULT_PORT, help="porta (padrão: 8765)")
    ui.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    return parser.parse_args(argv)


def _bind_ui_socket(port: int) -> socket.socket | None:
    """Reserva a porta em 127.0.0.1 com uso exclusivo; ocupada → None.

    Exclusivo de verdade: no Windows, o SO_REUSEADDR que o uvicorn liga deixaria duas
    instâncias na mesma porta, cada requisição caindo numa.
    """
    sock = socket.socket()
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
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

    def __init__(self, port: int = UI_DEFAULT_PORT, retry_seconds: float = 30.0) -> None:
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
        if args.command == "ui":
            validate_and_init_config()
            run_ui(args.port, open_browser=not args.no_browser)
            return 0

        if args.bootstrap:
            validate_and_init_config()
            print("bootstrap: OK")
            return 0

        if args.check_db:
            validate_config()
            result = check_database()
            print(f"database: {result['database']}")
            return 0 if result["status"] == "ok" else 1

        if args.migrate_v2:
            validate_config()
            from knowledge_os.db.rename_v2 import rename_v2
            from knowledge_os.db.session import create_db_engine

            # Engine cru, sem passar por get_engine()/init_db(): aquele caminho roda o
            # schema_sync aditivo primeiro, que criaria "projects"/"repo_links" vazias
            # antes do rename_v2 rodar — o pré-voo veria a tabela nova já existindo e
            # pularia o rename de verdade, perdendo os dados presos nas tabelas antigas.
            engine = create_db_engine()
            try:
                result = rename_v2(engine)
            finally:
                engine.dispose()
            print(json.dumps(result))
            return 0

        validate_and_init_config()
        # Diagnóstico das conexões em segundo plano: uma conexão fora do ar não pode
        # atrasar o handshake (o cliente MCP desiste em ~30 s).
        threading.Thread(target=_report_connections_safely, daemon=True).start()
        threading.Thread(target=_run_daily_safely, daemon=True).start()
        if ui_enabled():
            BackgroundUI().start()
        register_all_tools()
        mcp.run()
        return 0
    except KeyboardInterrupt:
        print("Encerrando...", file=sys.stderr)
        return 0
    except (ConfigError, DatabaseError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        close_engines()


if __name__ == "__main__":
    sys.exit(main())
