"""Exceções customizadas do MCP Knowledge OS."""


class ConfigError(Exception):
    """Configuração inválida ou incompleta."""


class DatabaseError(Exception):
    """Falha ao inicializar, consultar ou validar o banco de dados."""
