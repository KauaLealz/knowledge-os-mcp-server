"""Exceções customizadas do MCP Knowledge OS."""


class ConfigError(Exception):
    """Configuração inválida ou incompleta."""


class StorageError(Exception):
    """Falha ao ler ou gravar os arquivos de uma conexão."""


class NotFoundError(Exception):
    """Recurso solicitado não existe (equivalente a 404)."""


class ValidationError(Exception):
    """Entrada inválida ou conflitante (ex.: nome duplicado)."""


class NoConnectionError(ValidationError):
    """Nenhuma conexão configurada (ou nenhuma marcada como padrão)."""


class GitError(Exception):
    """Falha ao rodar `git` ou `gh` (clone, pull, push, PR, issue)."""
