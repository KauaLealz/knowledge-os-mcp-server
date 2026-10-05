"""Configuração do MCP Knowledge OS."""

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

if __name__ == "__main__":
    # `python src/knowledge_os/config.py` põe o pacote em sys.path[0]; troca por src/.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from knowledge_os.exceptions import ConfigError  # noqa: E402

logger = logging.getLogger(__name__)

MIN_DB_KEY_LENGTH = 16

# Home de dados: connections.json, banco catálogo, artifacts, exports e backups.
# As constantes são lidas no import; o diretório só é criado em ensure_home().
KNOWLEDGE_HOME: Path = (
    Path(os.getenv("KNOWLEDGE_OS_HOME") or Path.home() / ".knowledge-os").expanduser().resolve()
)
ARTIFACTS_DIR: Path = KNOWLEDGE_HOME / "artifacts"
EXPORTS_DIR: Path = KNOWLEDGE_HOME / "exports"
BACKUPS_DIR: Path = KNOWLEDGE_HOME / "backups"

_DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306}
_FORBIDDEN_CHARS = set("?#/\\@")

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
UI_DEFAULT_PORT = 8765  # UI local (127.0.0.1); o link para preencher segredos aponta para ela

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
    # Import tardio: knowledge_os.db.session importa este módulo.
    from knowledge_os.db.migrations import bootstrap

    bootstrap()


def config_error(exc: Exception) -> ConfigError:
    """ConfigError seguro para propagar: o texto de `exc` só passa se já for de ConfigError."""
    return exc if isinstance(exc, ConfigError) else ConfigError("connections.json inválido")


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

    @model_validator(mode="after")
    def shape_valid(self) -> "ConnectionConfig":
        if self.db_type == "sqlite":
            if not self.path:
                raise ValueError("path é obrigatório para SQLite")
            return self
        if self.port is None:
            self.port = _DEFAULT_PORTS[self.db_type]
        for field in ("host", "database"):
            if not getattr(self, field):
                raise ValueError(f"{field} é obrigatório")
        for field in ("host", "database", "username"):
            value = getattr(self, field)
            if value and any(ch in _FORBIDDEN_CHARS or ch.isspace() for ch in value):
                raise ValueError(f"{field} contém caracteres inválidos (? # / \\ @ ou espaço)")
        return self

    def resolved_path(self) -> str:
        """Path do SQLite; o relativo resolve contra o home no momento da chamada."""
        path = Path(self.path or "").expanduser()
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
    def _parse(path: Path) -> ConnectionsFile:
        """Lê o JSON; o erro diz onde (conexão e campo) sem ecoar valores (há senhas)."""
        try:
            return ConnectionsFile(**json.loads(path.read_text(encoding="utf-8")))
        except PydanticValidationError as exc:
            details = []
            for e in exc.errors(include_input=False):
                loc = list(e["loc"])
                where = ".".join(str(p) for p in loc)
                if loc[:1] == ["connections"] and len(loc) > 1 and isinstance(loc[1], int):
                    try:
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        cid = raw["connections"][loc[1]].get("id")
                        where = f"conexão {cid!r}: " + ".".join(str(p) for p in loc[2:])
                    except Exception:
                        pass
                details.append(f"{where}: {e['msg']}")
            raise ConfigError(f"connections.json inválido: {'; '.join(details)}") from None
        except (ValueError, OSError, TypeError, AttributeError):
            raise ConfigError("connections.json inválido: JSON malformado ou ilegível") from None

    @staticmethod
    def load_or_create() -> ConnectionsFile:
        """Carrega o arquivo, ou grava e devolve o default se ele não existe."""
        path = ConfigManager.CONNECTIONS_FILE
        if path.exists():
            return ConfigManager._parse(path)
        config = ConfigManager.create_default_config()
        ConfigManager.save(config)
        return config

    @staticmethod
    def save(config: ConnectionsFile) -> None:
        path = ConfigManager.CONNECTIONS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.model_dump(mode="json"), indent=2)
        # tmp único por processo/chamada (MCP + UI podem salvar ao mesmo tempo), só do dono.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        fd = os.open(tmp, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            try:
                os.replace(tmp, path)
            except OSError:  # Windows: destino aberto por outro processo (ex.: MCP + UI)
                path.write_text(payload, encoding="utf-8")
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def validate_connection(conn: ConnectionConfig) -> dict[str, str]:
        """Tenta conectar e rodar SELECT 1. A senha nunca aparece na mensagem de erro.

        Usa o engine do dialect, que tem connect_timeout: sem ele, uma porta fechada no
        Windows segura a conexão por ~130 s em vez de falhar em segundos.
        """
        from sqlalchemy import text

        from knowledge_os.db.dialects import get_dialect, redact

        url = conn.get_url()
        engine = None
        try:
            engine = get_dialect(conn.db_type).create_engine(url)
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return {"status": "ok", "message": "Connection successful"}
        except Exception as exc:
            return {"status": "error", "message": redact(str(exc), url)[:500]}
        finally:
            if engine is not None:
                engine.dispose()


if __name__ == "__main__":
    from knowledge_os.config import validate_and_init_config as _run

    logging.basicConfig(level=LOG_LEVEL)
    _run()
    print("config: OK")
