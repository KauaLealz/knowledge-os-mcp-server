"""Perfis de ferramentas: `all` (padrão, administração completa) e `agent` (enxuto).

Agentes pagam contexto por cada ferramenta exposta e o Cursor limita o total por sessão.
O perfil `agent` deixa só o que o fluxo de trabalho usa; a administração (conexões,
migração, export, tags, labels) fica com o perfil `all` e com a UI.
"""

import os
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

TOOLSET_ENV = "KNOWLEDGE_OS_TOOLSET"
AGENT_TOOLS = frozenset({
    "context_get", "item_search", "item_get", "item_upsert", "item_batch_upsert",
    "relation_create", "memory_promote", "project_link", "health_check",
})


def selected_toolset() -> str:
    """`agent` ou `all` (valor desconhecido cai em `all`, que não esconde nada)."""
    value = os.environ.get(TOOLSET_ENV, "all").strip().lower()
    return value if value in ("agent", "all") else "all"


class FilteredMCP:
    """Repassa ao FastMCP só as ferramentas permitidas; as demais são ignoradas."""

    def __init__(self, mcp: FastMCP, allowed: frozenset[str]) -> None:
        self._mcp = mcp
        self._allowed = allowed

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
        real = self._mcp.tool(*args, **kwargs)

        def decorator(fn: Callable[..., Any]) -> Any:
            return real(fn) if fn.__name__ in self._allowed else fn

        return decorator
