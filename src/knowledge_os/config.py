"""Configuração do MCP Knowledge OS."""

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

if __name__ == "__main__":
    # `python src/knowledge_os/config.py` põe o pacote em sys.path[0]; troca por src/.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from knowledge_os.exceptions import ConfigError  # noqa: E402

logger = logging.getLogger(__name__)

# Home de dados: connections.json, repos.json, contadores de uso e a fila offline.
# As constantes são lidas no import; o diretório só é criado em ensure_home().
KNOWLEDGE_HOME: Path = (
    Path(os.getenv("KNOWLEDGE_OS_HOME") or Path.home() / ".knowledge-os").expanduser().resolve()
)
# Clones git das conexões antigas, gravadas antes de a pasta ser escolhida pelo usuário.
REPOS_DIR: Path = KNOWLEDGE_HOME / "repos"

# Mensagem de toda operação que precisa de uma conexão quando não há nenhuma.
NO_CONNECTION_MESSAGE = (
    "Nenhuma conexão configurada. Crie uma com connection_create(name, path[, remote_url])."
)


def ensure_home() -> None:
    """Cria o home de dados (chamado pelos pontos de entrada)."""
    KNOWLEDGE_HOME.mkdir(parents=True, exist_ok=True)


# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
UI_DEFAULT_PORT = 8765  # UI local (127.0.0.1); o link para preencher segredos aponta para ela


def validate_config() -> None:
    """Valida a configuração na inicialização. Levanta ConfigError se inválida."""
    if not KNOWLEDGE_HOME.exists():
        raise ConfigError(f"Home de dados não existe: {KNOWLEDGE_HOME}")


def config_error(exc: Exception) -> ConfigError:
    """ConfigError seguro para propagar: o texto de `exc` só passa se já for de ConfigError."""
    return exc if isinstance(exc, ConfigError) else ConfigError("connections.json inválido")


class ConnectionConfig(BaseModel):
    """Uma conexão do connections.json do home: um repositório git (clone local).

    `path` é a pasta local do repositório, indicada pelo usuário na criação — já um
    repositório git (usado como está) ou uma pasta comum (`git init` nela). Sem
    `remote_url`, a connection é só esse repositório local (sem GitHub). Os itens são os
    arquivos dessa pasta: não há outra cópia deles.

    `path` é opcional só por compatibilidade com connections.json gravados antes dessa
    pasta ser escolhida pelo usuário — nelas o clone cai no home de dados, derivado do
    `id` (comportamento antigo). Toda connection nova exige `path` (`ConnectionService.create`).
    """

    id: str
    name: str
    path: str | None = None
    remote_url: str | None = None
    review_mode: Literal["direct", "pr"] = "direct"
    enabled: bool = True
    created_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def id_valid(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_-]+", v):
            raise ValueError("ID must be lowercase alphanumeric with hyphens/underscores")
        return v

    def clone_path(self) -> Path:
        """Diretório do repositório git desta connection."""
        return Path(self.path) if self.path else REPOS_DIR / self.id


# Id do catálogo das versões antigas; só aparece em connections.json antigos.
LEGACY_CATALOG_ID = "default"


class ConnectionsFile(BaseModel):
    """Conteúdo do connections.json do home. Sem conexões, `default` é None."""

    version: str = "1.0"
    default: str | None = None
    connections: list[ConnectionConfig] = []

    @model_validator(mode="before")
    @classmethod
    def _sem_catalogo_antigo(cls, data: Any) -> Any:
        """Versões antigas gravavam `default: "default"` (o catálogo, que não existe mais):
        sem uma conexão com esse id, vira "sem padrão" em vez de recusar o arquivo."""
        if isinstance(data, dict) and data.get("default") == LEGACY_CATALOG_ID:
            ids = [c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                   for c in data.get("connections") or []]
            if LEGACY_CATALOG_ID not in ids:
                data = {**data, "default": None}
        return data

    @model_validator(mode="after")
    def default_exists(self) -> "ConnectionsFile":
        if self.default is not None and self.default not in [c.id for c in self.connections]:
            raise ValueError(f"Default connection '{self.default}' not found")
        return self

    def get_connection(self, connection_id: str) -> ConnectionConfig:
        for conn in self.connections:
            if conn.id == connection_id:
                return conn
        raise ValueError(f"Connection '{connection_id}' not found")

    def get_default_connection(self) -> ConnectionConfig | None:
        return self.get_connection(self.default) if self.default else None


class ConfigManager:
    """Carrega, cria, salva e valida as conexões do arquivo de configuração."""

    CONNECTIONS_FILE = KNOWLEDGE_HOME / "connections.json"

    @staticmethod
    def create_default_config() -> ConnectionsFile:
        """Config inicial: nenhuma conexão e nenhuma padrão."""
        return ConnectionsFile(default=None, connections=[])

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
    def load() -> ConnectionsFile:
        """Carrega o arquivo; sem ele, a config vazia (nada é gravado só por ler)."""
        path = ConfigManager.CONNECTIONS_FILE
        if path.exists():
            return ConfigManager._parse(path)
        return ConfigManager.create_default_config()

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
        """Testa o repositório git da conexão: `git ls-remote` (rápido, não clona).

        Sem `remote_url` não há o que testar (repositório só local): sempre "ok". O erro
        de `ls-remote`, se houver, nunca ecoa segredo embutido na URL (token em HTTPS).
        """
        import subprocess

        from knowledge_os.services.secret_guard import find_secret

        if conn.remote_url is None:
            return {"status": "ok", "message": "Repositório local (sem remote)"}
        try:
            result = subprocess.run(
                ["git", "ls-remote", conn.remote_url],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "error", "message": str(exc)[:500]}
        if result.returncode == 0:
            return {"status": "ok", "message": "Connection successful"}
        stderr = result.stderr.strip()
        kind = find_secret(stderr)
        message = f"(saída oculta: parece conter {kind})" if kind else stderr
        return {"status": "error", "message": message[:500]}


if __name__ == "__main__":
    logging.basicConfig(level=LOG_LEVEL)
    ensure_home()
    validate_config()
    print("config: OK")
