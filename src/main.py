"""MCP Knowledge OS - Servidor Principal."""

import argparse
import logging
import sys
from pathlib import Path

if __name__ == "__main__":
    # `python src/main.py` põe src/ em sys.path[0], o que faria src/mcp/ sombrear o
    # pacote `mcp` real. Troca por a raiz do projeto.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from fastmcp import FastMCP  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from src.config import (  # noqa: E402
    LOG_LEVEL,
    ConfigManager,
    ensure_home,
    validate_and_init_config,
    validate_config,
)
from src.db.models import Base  # noqa: E402
from src.db.session import FTS_TABLE, close_engines, get_engine  # noqa: E402
from src.exceptions import ConfigError, DatabaseError  # noqa: E402

logger = logging.getLogger(__name__)

from src import __version__  # noqa: E402
from src.mcp.toolset import selected_toolset  # noqa: E402

UI_DEFAULT_PORT = 8765
_MCP_DIR = Path(__file__).resolve().parent / "mcp"
INSTRUCTIONS_FILE = _MCP_DIR / "INSTRUCTIONS.md"
AGENT_INSTRUCTIONS_FILE = _MCP_DIR / "INSTRUCTIONS_AGENT.md"
TOOLSET = selected_toolset()

# Inicializar FastMCP (as instructions chegam ao agente no handshake do protocolo e entram
# no contexto de toda sessão: o perfil `agent` usa a versão curta).
mcp = FastMCP(
    name="knowledge-mcp",
    instructions=(AGENT_INSTRUCTIONS_FILE if TOOLSET == "agent" else INSTRUCTIONS_FILE).read_text(
        encoding="utf-8"
    ),
)


def schema_version() -> str | None:
    """Versão do schema gravada no banco default (None se ainda não sincronizado)."""
    from src.db.schema_sync import SCHEMA_META_TABLE

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
    **Retorna:** {status: ok|error, database: connected | motivo, version, schema_version,
        toolset}.
    **Exemplo:** health_check()
    **Notas:** Valida a conexão e a presença de todas as tabelas (inclusive a de busca textual).
    """
    result = check_database()
    return {**result, "version": __version__, "schema_version": schema_version() or "",
            "toolset": TOOLSET}


def register_all_tools() -> None:
    """Registra os tools do perfil ativo: `agent` (6) ou `all` (+ administração)."""
    from src.mcp import admin_tools, agent_tools

    agent_tools.register(mcp)
    if TOOLSET == "all":
        admin_tools.register(mcp)


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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="knowledge-mcp", description="MCP Knowledge OS")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check-db", action="store_true", help="verifica conexão e schema do banco e sai"
    )
    group.add_argument(
        "--bootstrap", action="store_true", help="cria schema e labels padrão e sai"
    )
    sub = parser.add_subparsers(dest="command")
    ui = sub.add_parser("ui", help="sobe a UI web local (somente 127.0.0.1)")
    ui.add_argument("--port", type=int, default=UI_DEFAULT_PORT, help="porta (padrão: 8765)")
    ui.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    return parser.parse_args(argv)


def run_ui(port: int, open_browser: bool) -> None:
    """Sobe a UI/API em 127.0.0.1, sem login. A URL vai ao stdout (não é modo MCP)."""
    import socket

    import uvicorn

    from src.api.main import app

    # Testa o bind antes de anunciar a URL: porta ocupada = URL de outro processo.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise ConfigError(f"Porta {port} ocupada em 127.0.0.1; use --port") from None

    url = f"http://127.0.0.1:{port}/ui/"
    print(url, flush=True)
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


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

        validate_and_init_config()
        # Diagnóstico das conexões em segundo plano: uma conexão fora do ar não pode
        # atrasar o handshake (o cliente MCP desiste em ~30 s).
        import threading

        threading.Thread(target=_report_connections_safely, daemon=True).start()
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
