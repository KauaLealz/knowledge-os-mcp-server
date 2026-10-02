"""Testes do servidor principal."""

from src.main import mcp


def test_mcp_has_instructions():
    """FastMCP tem instructions setadas."""
    assert mcp.instructions is not None
    assert "Configurar conexões" in mcp.instructions
    assert "password_env" in mcp.instructions
    assert "enabled" in mcp.instructions


def test_instructions_descrevem_home_e_catalogo():
    assert "KNOWLEDGE_OS_HOME" in mcp.instructions
    assert "~/.knowledge-os" in mcp.instructions
    assert "knowledge.db" in mcp.instructions
