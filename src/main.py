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
from sqlalchemy import inspect, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.config import (  # noqa: E402
    LOG_LEVEL,
    ConfigManager,
    ConnectionConfig,
    validate_and_init_config,
    validate_config,
)
from src.db.models import DEFAULT_CONNECTION_ID, Base, Connection  # noqa: E402
from src.db.session import FTS_TABLE, close_engines, get_engine  # noqa: E402
from src.exceptions import ConfigError, DatabaseError  # noqa: E402

logger = logging.getLogger(__name__)

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


def import_legacy_connections() -> int:
    """Copia para o connections.json as conexões que só existem na tabela `connections`.

    Catálogos anteriores ao JSON único guardavam as conexões nessa tabela. A importação é
    idempotente (pula id ou nome já presentes) e devolve quantas conexões entraram. A senha
    não é migrada: o JSON só aceita `password_env`.
    """
    engine = get_engine()
    if not inspect(engine).has_table(Connection.__tablename__):
        return 0
    config = ConfigManager.load_or_create()
    known_ids = {c.id for c in config.connections}
    known_names = {c.name for c in config.connections}
    imported = 0
    with Session(engine) as s:
        rows = s.scalars(select(Connection).where(Connection.id != DEFAULT_CONNECTION_ID))
        for row in rows:
            if row.id in known_ids or row.name in known_names:
                continue
            url = make_url(row.db_url)
            fields = (
                {"path": url.database}
                if row.db_type == "sqlite"
                else {
                    "host": row.host or url.host,
                    "port": row.port or url.port,
                    "database": row.database or url.database,
                    "username": row.username or url.username,
                }
            )
            try:
                conn = ConnectionConfig(
                    id=row.id,
                    name=row.name,
                    db_type=row.db_type,
                    enabled=bool(row.is_active),
                    created_at=row.created_at,
                    **fields,
                )
            except ValueError as exc:
                logger.warning("Conexão legada %r ignorada: %s", row.name, exc)
                continue
            if url.password and url.password != "***":
                logger.warning(
                    "Conexão legada %r importada sem senha: defina password_env no JSON", row.name
                )
            config.connections.append(conn)
            known_ids.add(conn.id)
            known_names.add(conn.name)
            imported += 1
    if imported:
        ConfigManager.save(config)
        logger.info("%d conexão(ões) legada(s) importada(s) para o connections.json", imported)
    return imported


def report_connections() -> None:
    """Carrega (ou cria) .knowledge/connections.json e testa as conexões ativas.

    Escreve em stderr: o stdout é o canal do protocolo MCP.
    """
    import_legacy_connections()
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
