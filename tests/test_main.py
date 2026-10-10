"""Servidor principal: as instruções do handshake e o registro das ferramentas."""

import asyncio

from knowledge_os.main import mcp, register_all_tools
from knowledge_os.mcp.instructions import build_instructions


def test_mcp_usa_as_instrucoes_geradas():
    assert mcp.instructions == build_instructions()


def test_instrucoes_dizem_quando_ler_gravar_e_confirmar():
    text = mcp.instructions
    for word in ("item_search", "item_get", "item_save", "item_feedback", "repo(action=\"link\"",
                 "/plumb-setup", "pending.jsonl", "fill_url", "confirm=True", "connection_create"):
        assert word in text, word
    assert len(text.encode()) < 6000  # entram em toda sessão


def test_instrucoes_explicam_onde_mora_e_onde_vale():
    text = mcp.instructions
    for word in ("workspace", "project", "subject", "`scoped`", "`workspace`", "`global`",
                 "herda"):
        assert word in text, word
    for gone in ("context_get", "label_", "_rename", "memory_class", "insight", "sensivel"):
        assert gone not in text, gone


def test_instrucoes_citam_url_resumo_da_spec_e_tags_de_estado():
    text = mcp.instructions
    assert "`url`" in text
    assert "<estado> · <fase n/total> · <branch> · <worktree> · <agente>" in text
    for tag in ("aguardando-aprovacao", "em-andamento", "parada"):
        assert tag in text, tag


def test_register_all_tools_registra_as_32():
    register_all_tools()
    assert len(asyncio.run(mcp.list_tools())) == 32
