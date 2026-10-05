"""Perfis de ferramentas: `all` (padrão, com administração) e `agent` (só o fluxo).

Agentes pagam contexto por cada ferramenta exposta e o Cursor limita o total por sessão.
O perfil `agent` deixa só o que o fluxo de trabalho usa; a administração (conexões,
migração, export, tags, labels) fica com o perfil `all` e com a UI.
"""

import os

TOOLSET_ENV = "KNOWLEDGE_OS_TOOLSET"
AGENT_TOOLS = frozenset({
    "context_get", "item_search", "item_get", "item_save", "project_link", "health_check",
})


def selected_toolset() -> str:
    """`agent` ou `all` (valor desconhecido cai em `all`, que não esconde nada)."""
    value = os.environ.get(TOOLSET_ENV, "all").strip().lower()
    return value if value in ("agent", "all") else "all"
