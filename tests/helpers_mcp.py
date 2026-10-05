"""Adaptadores da API do fastmcp 4 usados pelos testes.

O fastmcp 4 trocou `get_tools()` (dict) por `list_tools()` (lista) e passou a devolver
`ToolResult` / `CallToolResult` com `.content`, em vez da lista de blocos.
"""

import asyncio
from typing import Any

from fastmcp import Client, FastMCP


def tools_by_name(server: FastMCP) -> dict[str, Any]:
    """Ferramentas registradas, por nome."""
    return {t.name: t for t in asyncio.run(server.list_tools())}


def run_tool(server: FastMCP, name: str, args: dict[str, Any]) -> list[Any]:
    """Executa a ferramenta direto no servidor e devolve os blocos de conteúdo."""
    tool = asyncio.run(server.get_tool(name))
    return list(asyncio.run(tool.run(args)).content)


def client_call(server: FastMCP, name: str, args: dict[str, Any]) -> list[Any]:
    """Executa a ferramenta por um cliente MCP em memória e devolve os blocos de conteúdo."""

    async def run() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, args)

    return list(asyncio.run(run()).content)
