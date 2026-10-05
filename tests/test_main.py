"""Testes do servidor principal."""

from knowledge_os.main import mcp


def test_mcp_has_instructions():
    """Instruções enxutas: dizem quando ler, quando gravar e com que ferramentas."""
    assert mcp.instructions is not None
    for word in ("context_get", "item_search", "item_get", "item_save", "/plumb-setup"):
        assert word in mcp.instructions, word
    assert len(mcp.instructions.encode()) < 3000  # entram em toda sessão


def test_instructions_nao_pedem_senha_e_apontam_ui_para_conexoes():
    assert "knowledge-mcp ui" in mcp.instructions
    assert "Senhas nunca passam pela conversa" in mcp.instructions
