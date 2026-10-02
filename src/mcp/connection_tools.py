"""Tools MCP de Connection (gerência de conexões a bancos)."""

import logging
from typing import Any

from fastmcp import FastMCP
from sqlalchemy import Engine, text

from src.config import ConfigManager, ConnectionConfig
from src.services._common import connection_to_dict
from src.services.connection_service import ConnectionService

logger = logging.getLogger(__name__)

MIGRATION_MODES = ("replace", "merge")


def _open_engine(conn: ConnectionConfig) -> Engine:
    from src.db.session import create_db_engine

    return create_db_engine(conn.get_url())


def connection_init_db(connection_id: str) -> dict[str, Any]:
    """Cria o schema (tabelas, índices e busca textual) de uma connection.

    **Use quando:** Logo depois de cadastrar um banco novo, antes de workspace_create ou
        migrate_workspaces.
    **Retorna:** {connection_id, status: initialized|error, db_type, message}.
    **Exemplo:** connection_init_db(connection_id="postgres_prod")
    **Notas:** Idempotente. Retorna status=error se o banco não estiver acessível. A connection
        precisa estar no .knowledge/connections.json.
    """
    try:
        conn = ConfigManager.load_or_create().get_connection(connection_id)
        validation = ConfigManager.validate_connection(conn)
        if validation["status"] != "ok":
            return {
                "connection_id": connection_id,
                "status": "error",
                "message": f"Cannot connect: {validation['message']}",
            }
        from src.db.session import init_db

        engine = _open_engine(conn)
        try:
            if conn.db_type == "postgresql":
                with engine.begin() as c:
                    c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            init_db(engine, connection_id=conn.id, connection_name=conn.name)
        finally:
            engine.dispose()
        return {
            "connection_id": connection_id,
            "status": "initialized",
            "db_type": conn.db_type,
            "message": "Database schema initialized successfully",
        }
    except Exception as exc:
        return {"connection_id": connection_id, "status": "error", "message": str(exc)}


def _clear_target(conn: ConnectionConfig) -> None:
    """Modo replace: apaga os dados de conhecimento do destino (ordem inversa das FKs)."""
    from src.services.migration_service import TABLES

    engine = _open_engine(conn)
    try:
        with engine.begin() as c:
            for table in reversed(TABLES):
                c.execute(text(f"DELETE FROM {table}"))
    finally:
        engine.dispose()


def migrate_workspaces(
    from_connection_id: str, to_connection_id: str, mode: str = "replace"
) -> dict[str, Any]:
    """Copia workspaces (domains, items, tags, labels, relations, artifacts) entre connections.

    **Use quando:** Mover o conhecimento de SQLite para PostgreSQL/MySQL, ou consolidar duas bases.
    **Retorna:** {status: success|error, workspaces_migrated, items_migrated, artifacts_migrated,
        duration_seconds, message}.
    **Exemplo:** migrate_workspaces(from_connection_id="sqlite_local",
        to_connection_id="postgres_prod", mode="replace")
    **Notas:** mode=replace apaga os dados do destino antes de copiar; mode=merge une tags/labels
        por nome e aborta se algum id já existir. Origem e destino devem ser diferentes, habilitados
        e o destino já inicializado (connection_init_db).
    """
    try:
        if mode not in MIGRATION_MODES:
            return {"status": "error", "message": "mode must be 'replace' or 'merge'"}
        config = ConfigManager.load_or_create()
        src = config.get_connection(from_connection_id)
        dst = config.get_connection(to_connection_id)
        if from_connection_id == to_connection_id:
            return {"status": "error", "message": "Source and target must differ"}
        for label, cid, c in (
            ("Source", from_connection_id, src),
            ("Target", to_connection_id, dst),
        ):
            if not c.enabled:
                return {"status": "error", "message": f"{label} '{cid}' disabled"}
            val = ConfigManager.validate_connection(c)
            if val["status"] != "ok":
                return {
                    "status": "error",
                    "message": f"Cannot connect to '{cid}': {val['message']}",
                }

        import time

        from src.services.migration_service import MigrationService

        started = time.perf_counter()
        if mode == "replace":
            _clear_target(dst)
        result = MigrationService().migrate(src.get_url(), dst.get_url())
        if result["errors"]:
            return {"status": "error", "message": "; ".join(result["errors"])}
        return {
            "from_connection": from_connection_id,
            "to_connection": to_connection_id,
            "mode": mode,
            "status": "success",
            "workspaces_migrated": result["workspaces"],
            "items_migrated": result["items"],
            "artifacts_migrated": result["artifacts"],
            "duration_seconds": round(time.perf_counter() - started, 3),
            "message": "Migration completed successfully",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def register(mcp: FastMCP) -> None:
    """Registra as 8 tools de connection no servidor."""
    mcp.tool()(connection_init_db)
    mcp.tool()(migrate_workspaces)

    @mcp.tool()
    def connection_create(
        name: str,
        db_type: str,
        url: str,
        test: bool = True,
    ) -> dict[str, Any]:
        """Registra uma nova connection a um banco (sqlite, mysql ou postgresql).

        **Use quando:** Conectar um banco novo ou remoto antes de usá-lo via connection_id nos
            outros tools.
        **Retorna:** Dados da connection (id, name, db_type, url sem senha, is_active). A senha
            nunca é devolvida.
        **Exemplo:** connection_create(name="postgres_prod", db_type="postgresql",
            url="postgresql://user:pass@host:5432/knowledge")
        **Notas:** Exemplos de url: sqlite:///./database/x.db, mysql://user:pass@host/db. Com
            test=True (padrão) a conexão é testada antes de ser gravada. Depois rode
            connection_init_db.
        """
        conn = ConnectionService().create(name, db_type, url, test=test)
        return connection_to_dict(conn)

    @mcp.tool()
    def connection_list() -> list[dict[str, Any]]:
        """Lista as connections cadastradas.

        **Use quando:** Primeiro passo de qualquer sessão: descobrir os connection_id disponíveis.
        **Retorna:** Lista de connections (id, name, db_type, url sem senha, is_active).
        **Exemplo:** connection_list()
        **Notas:** A connection default sqlite_local existe desde o início. Sem parâmetros.
        """
        return [connection_to_dict(c) for c in ConnectionService().list()]

    @mcp.tool()
    def connection_get(connection_id: str) -> dict[str, Any]:
        """Obtém uma connection pelo id ou nome.

        **Use quando:** Conferir configuração/estado de uma connection específica.
        **Retorna:** Dados da connection (sem senha).
        **Exemplo:** connection_get(connection_id="postgres_prod")
        **Notas:** Erro de not found se não existir; use connection_list para ver os ids.
        """
        return connection_to_dict(ConnectionService().get(connection_id))

    @mcp.tool()
    def connection_delete(connection_id: str) -> dict[str, Any]:
        """Remove uma connection e os workspaces do catálogo ligados a ela.

        **Use quando:** Descartar uma connection que não será mais usada.
        **Retorna:** {status: deleted|not_found, message}.
        **Exemplo:** connection_delete(connection_id="postgres_old")
        **Notas:** Remove o registro e o catálogo; não apaga o banco remoto. Confirme com o usuário
            antes de usar.
        """
        if ConnectionService().delete(connection_id):
            return {"status": "deleted", "message": f"Conexão '{connection_id}' removida"}
        return {"status": "not_found", "message": f"Conexão '{connection_id}' não existe"}

    @mcp.tool()
    def connection_test(connection_id: str) -> dict[str, Any]:
        """Testa a conectividade de uma connection (conecta, cria e remove uma tabela dummy).

        **Use quando:** Depois de connection_create, ou ao diagnosticar erros de conexão.
        **Retorna:** {status: ok|error, message, latency_ms}.
        **Exemplo:** connection_test(connection_id="postgres_prod")
        **Notas:** Exige permissão de CREATE TABLE no banco. Mensagens de erro vêm com a senha
            redigida.
        """
        return ConnectionService().test(connection_id)

    @mcp.tool()
    def connection_update(
        connection_id: str,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        """Atualiza o nome e/ou o estado ativo de uma connection.

        **Use quando:** Renomear uma connection ou desativá-la sem apagar.
        **Retorna:** Dados atualizados da connection.
        **Exemplo:** connection_update(connection_id="postgres_prod", is_active=False)
        **Notas:** Só os campos informados mudam. Não altera a URL: para isso crie outra connection.
        """
        fields = {
            k: v for k, v in dict(name=name, is_active=is_active).items() if v is not None
        }
        return connection_to_dict(ConnectionService().update(connection_id, **fields))
