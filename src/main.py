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

from src.config import LOG_LEVEL, validate_and_init_config, validate_config  # noqa: E402
from src.db.models import Base  # noqa: E402
from src.db.session import FTS_TABLE, close_engine, get_engine  # noqa: E402
from src.exceptions import ConfigError, DatabaseError  # noqa: E402

logger = logging.getLogger(__name__)

# Inicializar FastMCP
mcp = FastMCP(name="knowledge-mcp")


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
    """Verifica saúde do servidor MCP."""
    return check_database()


def register_all_tools() -> None:
    """Registra todos os tools no FastMCP."""
    from src.mcp import domain_tools, workspace_tools

    workspace_tools.register(mcp)
    domain_tools.register(mcp)
    # T3+ completarão isso depois


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="knowledge-mcp", description="MCP Knowledge OS")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check-db", action="store_true", help="verifica conexão e schema do banco e sai"
    )
    group.add_argument(
        "--bootstrap", action="store_true", help="cria schema e labels padrão e sai"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada principal. Retorna o código de saída."""
    args = _parse_args(argv)
    logging.basicConfig(level=LOG_LEVEL, stream=sys.stderr)
    try:
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
        close_engine()


if __name__ == "__main__":
    sys.exit(main())
