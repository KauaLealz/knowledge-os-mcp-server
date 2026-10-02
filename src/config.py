"""Configuração do MCP Knowledge OS."""

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator, model_validator

if __name__ == "__main__":
    # `python src/config.py` põe src/ em sys.path[0]; troca pela raiz do projeto.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from src.exceptions import ConfigError  # noqa: E402

logger = logging.getLogger(__name__)

MIN_DB_KEY_LENGTH = 16

# Home de dados: connections.json, banco catálogo, artifacts, exports e backups.
# As constantes são lidas no import; o diretório só é criado em ensure_home().
KNOWLEDGE_HOME: Path = Path(
    os.getenv("KNOWLEDGE_OS_HOME") or Path.home() / ".knowledge-os"
).expanduser()
ARTIFACTS_DIR: Path = KNOWLEDGE_HOME / "artifacts"
EXPORTS_DIR: Path = KNOWLEDGE_HOME / "exports"
BACKUPS_DIR: Path = KNOWLEDGE_HOME / "backups"

# Id reservado do catálogo (banco padrão, virtual: não consta da lista de conexões).
CATALOG_ID = "default"


def ensure_home() -> None:
    """Cria o home de dados e seus subdiretórios (chamado pelos pontos de entrada)."""
    for d in (KNOWLEDGE_HOME, ARTIFACTS_DIR, EXPORTS_DIR, BACKUPS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


# Database
DB_PATH: str = os.getenv("MCP_DB_PATH", str(KNOWLEDGE_HOME / "knowledge.db"))
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

    if not KNOWLEDGE_HOME.exists():
        raise ConfigError(f"Home de dados não existe: {KNOWLEDGE_HOME}")

    if not Path(DB_PATH).parent.exists():
        raise ConfigError(f"Diretório do banco não existe: {Path(DB_PATH).parent}")


def validate_and_init_config() -> None:
    """Valida a configuração e executa o bootstrap do banco de dados."""
    validate_config()
    # Import tardio: src.db.session importa este módulo.
    from src.db.migrations import bootstrap

    bootstrap()


class ConnectionConfig(BaseModel):
    """Uma conexão do connections.json do home (SQLite, PostgreSQL ou MySQL)."""

    id: str
    name: str
    db_type: Literal["sqlite", "postgresql", "mysql"]
    path: str | None = None  # SQLite
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    # Texto no connections.json (que vive no home, fora do repo). Nunca em repr/log/erro.
    password: str | None = Field(default=None, repr=False)
    enabled: bool = True
    created_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def id_valid(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_-]+", v):
            raise ValueError("ID must be lowercase alphanumeric with hyphens/underscores")
        return v

    @field_validator("id")
    @classmethod
    def id_not_reserved(cls, v: str) -> str:
        if v == CATALOG_ID:
            raise ValueError(f"ID '{CATALOG_ID}' is reserved")
        return v

    @field_validator("port")
    @classmethod
    def port_valid(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 65535:
            raise ValueError("Port must be 1-65535")
        return v

    def resolved_path(self) -> str:
        """Path do SQLite; o relativo resolve contra o home no momento da chamada."""
        path = Path(self.path or "")
        return (path if path.is_absolute() else KNOWLEDGE_HOME / path).as_posix()

    def get_url(self) -> str:
        """URL SQLAlchemy da conexão (com a senha do campo `password`)."""
        if self.db_type == "sqlite":
            return f"sqlite:///{self.resolved_path()}"
        user = quote(self.username or "", safe="")
        password = self.password or ""
        if password:
            userinfo = f"{user}:{quote(password, safe='')}@"
        else:
            userinfo = f"{user}@" if user else ""
        scheme = "postgresql" if self.db_type == "postgresql" else "mysql+pymysql"
        return f"{scheme}://{userinfo}{self.host}:{self.port}/{self.database}"


class ConnectionsFile(BaseModel):
    """Conteúdo do connections.json do home."""

    version: str = "1.0"
    default: str
    connections: list[ConnectionConfig]

    @model_validator(mode="after")
    def default_exists(self) -> "ConnectionsFile":
        if self.default != CATALOG_ID and self.default not in [c.id for c in self.connections]:
            raise ValueError(f"Default connection '{self.default}' not found")
        return self

    def get_connection(self, connection_id: str) -> ConnectionConfig:
        for conn in self.connections:
            if conn.id == connection_id:
                return conn
        raise ValueError(f"Connection '{connection_id}' not found")

    def get_default_connection(self) -> ConnectionConfig:
        return self.get_connection(self.default)


class ConfigManager:
    """Carrega, cria, salva e valida as conexões do arquivo de configuração."""

    CONNECTIONS_FILE = KNOWLEDGE_HOME / "connections.json"

    @staticmethod
    def create_default_config() -> ConnectionsFile:
        """Config inicial: só o catálogo (`default`, <home>/knowledge.db), sem conexões extras."""
        return ConnectionsFile(default=CATALOG_ID, connections=[])

    @staticmethod
    def load_or_create() -> ConnectionsFile:
        """Carrega o arquivo, ou grava e devolve o default se ele não existe."""
        path = ConfigManager.CONNECTIONS_FILE
        if path.exists():
            return ConnectionsFile(**json.loads(path.read_text(encoding="utf-8")))
        config = ConfigManager.create_default_config()
        ConfigManager.save(config)
        return config

    @staticmethod
    def save(config: ConnectionsFile) -> None:
        path = ConfigManager.CONNECTIONS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(config.model_dump(mode="json"), indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # best-effort: o arquivo guarda senhas
        except OSError:
            pass
        try:
            os.replace(tmp, path)
        except OSError:  # Windows: destino aberto por outro processo (ex.: MCP + UI)
            path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
            tmp.unlink(missing_ok=True)

    @staticmethod
    def validate_connection(conn: ConnectionConfig) -> dict[str, str]:
        """Tenta conectar e rodar SELECT 1. A senha nunca aparece na mensagem de erro."""
        from sqlalchemy import create_engine, text

        from src.db.dialects import redact

        url = conn.get_url()
        engine = None
        try:
            engine = create_engine(url)
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return {"status": "ok", "message": "Connection successful"}
        except Exception as exc:
            return {"status": "error", "message": redact(str(exc), url)[:500]}
        finally:
            if engine is not None:
                engine.dispose()


if __name__ == "__main__":
    from src.config import validate_and_init_config as _run

    logging.basicConfig(level=LOG_LEVEL)
    _run()
    print("config: OK")
