"""Interface comum dos dialects de banco e utilitários de URL."""

from importlib.util import find_spec
from typing import Any
from urllib.parse import quote, quote_plus

from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from knowledge_os.exceptions import DatabaseError, ValidationError

FTS_TABLE = "items_fts"
FTS_COLUMNS = ("title", "summary", "keywords", "content")
# Peso de cada coluna no BM25 (mesma ordem de FTS_COLUMNS): o título decide mais que o corpo.
FTS_WEIGHTS = (6.0, 3.0, 4.0, 1.0)
# Sem acentos no índice: "migração" e "migracao" casam (a consulta passa pelo mesmo tokenizer).
FTS_TOKENIZE = "unicode61 remove_diacritics 2"

# Nome do backend na URL -> tipo canônico
_BACKEND_TYPES = {
    "sqlite": "sqlite",
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgresql": "postgresql",
    "postgres": "postgresql",
}
# Tipo canônico -> drivername completo quando a URL não informa o driver
_DEFAULT_DRIVERS = {"mysql": "mysql+pymysql", "postgresql": "postgresql+psycopg"}

CONNECT_TIMEOUT_S = 5


def require_driver(module: str, extra: str) -> None:
    """Falha com instrução clara quando o driver opcional não está instalado."""
    if find_spec(module) is None:
        raise DatabaseError(f"Driver {module!r} ausente: instale knowledge-mcp[{extra}]")


def detect_type(url: str) -> str:
    """Retorna "sqlite", "mysql" ou "postgresql". Levanta ValidationError se não suportado."""
    try:
        backend = make_url(url).get_backend_name()
    except ArgumentError as exc:
        raise ValidationError("URL de banco inválida") from exc
    try:
        return _BACKEND_TYPES[backend]
    except KeyError:
        raise ValidationError(
            f"Banco não suportado: {backend!r} (use sqlite, mysql ou postgresql)"
        ) from None


def normalize_url(url: str) -> str:
    """Completa o driver (pymysql / psycopg) quando a URL só traz o nome do banco."""
    db_type = detect_type(url)
    if db_type == "sqlite":
        return url
    parsed = make_url(url)
    if "+" in parsed.drivername and parsed.get_backend_name() != "mariadb":
        return url
    return parsed.set(drivername=_DEFAULT_DRIVERS[db_type]).render_as_string(hide_password=False)


def redact(message: str, url: str) -> str:
    """Remove a senha da URL de uma mensagem (erros de driver podem ecoá-la)."""
    try:
        password = make_url(url).password
    except ArgumentError:
        return message
    if password:
        for variant in {password, quote(password, safe=""), quote_plus(password)}:
            message = message.replace(variant, "***")
    return message


class DatabaseDialect:
    """Contrato de cada banco suportado. Todos os métodos são estáticos."""

    @staticmethod
    def create_engine(url: str) -> Engine:
        raise NotImplementedError

    @staticmethod
    def supports_fts() -> bool:
        raise NotImplementedError

    @staticmethod
    def create_fts_table(engine: Engine) -> None:
        """Cria a infraestrutura de busca textual (idempotente)."""
        raise NotImplementedError

    @staticmethod
    def search_parts(query: str) -> tuple[str, str, str, dict[str, Any]]:
        """Partes do SELECT de busca: (fonte, where, expressão de score, params).

        A fonte deve expor a tabela items com o alias `i`.
        """
        raise NotImplementedError

    @staticmethod
    def detect_from_url(url: str) -> str:
        return detect_type(url)
