"""Exceções customizadas do MCP Knowledge OS."""


class ConfigError(Exception):
    """Configuração inválida ou incompleta."""


class DatabaseError(Exception):
    """Falha ao inicializar, consultar ou validar o banco de dados."""


class NotFoundError(Exception):
    """Recurso solicitado não existe (equivalente a 404)."""


class ValidationError(Exception):
    """Entrada inválida ou conflitante (ex.: nome duplicado)."""

