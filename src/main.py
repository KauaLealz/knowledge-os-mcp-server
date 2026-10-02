"""MCP Knowledge OS - Servidor Principal."""

import sys
from fastmcp import FastMCP

from src.config import validate_config
from src.db.session import get_engine, close_engine

# Inicializar FastMCP
mcp = FastMCP(
    name="knowledge-mcp",
    implementation="knowledge-os/0.1.0",
)


@mcp.tool()
def health_check() -> dict:
    """Verifica saúde do servidor MCP."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}


# Os tools específicos serão importados de:
# - mcp/workspace_tools.py
# - mcp/domain_tools.py
# - mcp/item_tools.py
# - mcp/relation_tools.py
# - mcp/memory_tools.py
# - mcp/tag_tools.py
# - mcp/artifact_tools.py


def register_all_tools():
    """Registra todos os tools no FastMCP."""
    # TODO: Implementar quando os serviços forem criados
    # from src.mcp import workspace_tools, domain_tools, ...
    # workspace_tools.register(mcp)
    # domain_tools.register(mcp)
    # ...
    pass


def main():
    """Ponto de entrada principal."""
    try:
        # Validar configuração
        validate_config()

        # Inicializar banco de dados
        engine = get_engine()

        # Registrar todos os tools
        register_all_tools()

        # Iniciar servidor MCP
        mcp.run()

    except KeyboardInterrupt:
        print("Encerrando...", file=sys.stderr)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        close_engine()


if __name__ == "__main__":
    main()
