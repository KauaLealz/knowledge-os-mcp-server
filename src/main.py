"""MCP Knowledge OS - Servidor Principal."""

import argparse
import logging
import secrets
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

UI_DEFAULT_PORT = 8765
INSTRUCTIONS_FILE = Path(__file__).resolve().parent / "mcp" / "INSTRUCTIONS.md"

# Inicializar FastMCP (as instructions chegam ao agente no handshake do protocolo)
mcp = FastMCP(name="knowledge-mcp", instructions=INSTRUCTIONS_FILE.read_text(encoding="utf-8"))


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
    **Retorna:** {status: ok|error, database: connected | motivo do erro}.
    **Exemplo:** health_check()
    **Notas:** Valida a conexão e a presença de todas as tabelas (inclusive a de busca textual).
    """
    return check_database()


def register_all_tools() -> None:
    """Registra todos os tools no FastMCP."""
    from src.mcp import (
        artifact_tools,
        connection_tools,
        domain_tools,
        item_tools,
        label_tools,
        memory_tools,
        relation_tools,
        tag_tools,
        workspace_tools,
    )

    workspace_tools.register(mcp)
    domain_tools.register(mcp)
    item_tools.register(mcp)
    relation_tools.register(mcp)
    memory_tools.register(mcp)
    tag_tools.register(mcp)
    label_tools.register(mcp)
    artifact_tools.register(mcp)
    connection_tools.register(mcp)  # schema_sync, migrate_workspaces e 6 de connection


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
    ui = sub.add_parser("ui", help="sobe a UI web local (somente 127.0.0.1) com token por start")
    ui.add_argument("--port", type=int, default=UI_DEFAULT_PORT, help="porta (padrão: 8765)")
    ui.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    return parser.parse_args(argv)


def run_ui(port: int, open_browser: bool) -> None:
    """Sobe a UI/API em 127.0.0.1 com um token novo. A URL vai ao stdout (não é modo MCP)."""
    import uvicorn

    from src.api import auth
    from src.api.main import app

    token = secrets.token_urlsafe(32)
    auth.set_token(token)
    url = f"http://127.0.0.1:{port}/ui/#token={token}"
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
        report_connections()
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
