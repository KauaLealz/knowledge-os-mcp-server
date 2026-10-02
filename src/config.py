"""Configuração do MCP Knowledge OS."""

import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote

if __name__ == "__main__":
    # `python src/config.py` põe src/ em sys.path[0]; troca pela raiz do projeto.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from src.exceptions import ConfigError  # noqa: E402

logger = logging.getLogger(__name__)

MIN_DB_KEY_LENGTH = 16

# Diretórios
PROJECT_ROOT: Path = Path(__file__).parent.parent
DATABASE_DIR: Path = PROJECT_ROOT / "database"
ARTIFACTS_DIR: Path = PROJECT_ROOT / "artifacts"
EXPORTS_DIR: Path = PROJECT_ROOT / "exports"
BACKUPS_DIR: Path = PROJECT_ROOT / "backups"

# Criar diretórios se não existirem
for _d in (DATABASE_DIR, ARTIFACTS_DIR, EXPORTS_DIR, BACKUPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


# Database
DB_PATH: str = os.getenv("MCP_DB_PATH", str(DATABASE_DIR / "knowledge.db"))
DB_KEY: str | None = os.getenv("MCP_DB_KEY") or None
# SQLCipher é usado quando há chave, ou quando solicitado via MCP_USE_SQLCIPHER.
SQLCIPHER_REQUESTED: bool = _env_flag("MCP_USE_SQLCIPHER")
USE_SQLCIPHER: bool = DB_KEY is not None

# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

if SQLCIPHER_REQUESTED and DB_KEY is None:
    logger.warning(
        "SQLCipher solicitado (MCP_USE_SQLCIPHER) mas MCP_DB_KEY não está definido; "
        "usando SQLite sem criptografia"
    )


def _build_db_url() -> str:
    """Monta a URL SQLAlchemy conforme SQLCipher esteja ou não em uso."""
    if USE_SQLCIPHER and DB_KEY is not None:
        # SQLCipher com criptografia AES-256 (PRAGMA key via senha da URL)
        return f"sqlite+pysqlcipher://:{quote(DB_KEY, safe='')}@/{DB_PATH}"
    return f"sqlite:///{DB_PATH}"


# SQLAlchemy URL
DB_URL: str = _build_db_url()


def validate_config() -> None:
    """Valida configuração na inicialização. Levanta ConfigError se inválida."""
    # A chave só é validada quando SQLCipher está em uso; SQLite simples a ignora.
    if USE_SQLCIPHER and DB_KEY is not None and len(DB_KEY) < MIN_DB_KEY_LENGTH:
        raise ConfigError(f"MCP_DB_KEY deve ter no mínimo {MIN_DB_KEY_LENGTH} caracteres")

    if not DATABASE_DIR.exists():
        raise ConfigError(f"DATABASE_DIR não existe: {DATABASE_DIR}")

    if not Path(DB_PATH).parent.exists():
        raise ConfigError(f"Diretório do banco não existe: {Path(DB_PATH).parent}")


def validate_and_init_config() -> None:
    """Valida a configuração e executa o bootstrap do banco de dados."""
    validate_config()
    # Import tardio: src.db.session importa este módulo.
    from src.db.migrations import bootstrap

    bootstrap()


if __name__ == "__main__":
    from src.config import validate_and_init_config as _run

    logging.basicConfig(level=LOG_LEVEL)
    _run()
    print("config: OK")
