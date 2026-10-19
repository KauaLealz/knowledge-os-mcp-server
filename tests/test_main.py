"""Servidor principal: as instruções do handshake e o registro das ferramentas (v6)."""

import asyncio

from knowledge_os.main import mcp, register_all_tools
from knowledge_os.mcp.instructions import build_instructions


def test_mcp_usa_as_instrucoes_geradas():
    assert mcp.instructions == build_instructions()


def test_instrucoes_dizem_quando_ler_gravar_e_confirmar():
    text = mcp.instructions
    for word in ("item_search", "item_get", "item_save", "repo(action=\"link\"",
                 "/plumb-setup", "pending.jsonl", "fill_url", "confirm=True", "connection_create"):
        assert word in text, word
    # Feedback saiu do v6: o agente corrige ou remove o item.
    assert "item_feedback" not in text
    assert len(text.encode()) < 6000  # entram em toda sessão


def test_instrucoes_explicam_hierarquia_sem_scope():
    text = mcp.instructions
    for word in ("workspace", "project", "subject", "hierarquia"):
        assert word in text, word
    # v6 não tem scope/status/subtype/origin/feedback como campo.
    for gone in ("context_get", "memory_class", "insight", "effective_scope", "item_feedback"):
        assert gone not in text, gone


def test_instrucoes_citam_url_tags_de_ciclo_e_links():
    text = mcp.instructions
    assert "`url`" in text
    for tag in ("draft", "active", "done", "archived"):
        assert tag in text, tag
    for rel in ("depends_on", "relates_to"):
        assert rel in text, rel


def test_register_all_tools_registra_as_31():
    register_all_tools()
    assert len(asyncio.run(mcp.list_tools())) == 31
