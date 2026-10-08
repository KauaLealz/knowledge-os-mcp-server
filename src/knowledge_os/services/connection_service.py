"""Connection service: CRUD e teste de conexões (uma pasta local / repositório git cada).

O cadastro é o connections.json do home. Não há conexão implícita: a primeira criada vira a
padrão; remover a padrão passa o posto para outra habilitada (ou deixa sem padrão).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from knowledge_os.config import (
    ConfigManager,
    ConnectionConfig,
    ConnectionsFile,
    config_error,
)
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import refuse_home_source
from knowledge_os.services.brain import utcnow
from knowledge_os.services.git_repo_service import GitRepoService
from knowledge_os.storage import access

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = ("name", "is_active", "remote_url", "review_mode")
_json_lock = threading.RLock()  # protege o ciclo carregar -> alterar -> gravar do JSON
# Último teste de cada conexão: só em memória, por processo (some ao reiniciar).
_last_tests: dict[str, dict[str, Any]] = {}


def _remember_test(connection_id: str, result: dict[str, str], latency_ms: int) -> dict[str, Any]:
    last = {
        "status": result["status"],
        "message": result["message"],
        "latency_ms": latency_ms,
        "tested_at": utcnow(),
    }
    _last_tests[connection_id] = last
    return last


@dataclass
class Connection:
    """Conexão como o service a devolve: o cadastro + padrão + o último teste (em memória)."""

    id: str
    name: str
    path: str | None
    remote_url: str | None
    review_mode: str
    is_active: bool
    is_default: bool
    created_at: datetime | None
    last_test: dict[str, Any] | None = field(default=None)

    @property
    def last_tested(self) -> datetime | None:
        return self.last_test["tested_at"] if self.last_test else None

    @property
    def test_result(self) -> str | None:
        return self.last_test["message"] if self.last_test else None


def _to_row(conn: ConnectionConfig, default_id: str | None) -> Connection:
    return Connection(
        id=conn.id, name=conn.name, path=conn.path, remote_url=conn.remote_url,
        review_mode=conn.review_mode, is_active=conn.enabled,
        is_default=conn.id == default_id, created_at=conn.created_at,
        last_test=_last_tests.get(conn.id),
    )


def _validated_path(path: str) -> str:
    """Pasta local do repositório: absoluta, fora do home de dados.

    Não precisa existir ainda (`ensure_clone` cria); se existir, precisa ser uma pasta
    (nunca um arquivo).
    """
    raw = (path or "").strip()
    if not raw:
        raise ValidationError("path é obrigatório")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValidationError(f"path deve ser absoluto: {raw}")
    if candidate.exists() and not candidate.is_dir():
        raise ValidationError(f"path não é uma pasta: {raw}")
    refuse_home_source(candidate)
    resolved = candidate.resolve() if candidate.exists() else candidate
    return str(resolved)


def _load() -> ConnectionsFile:
    try:
        return ConfigManager.load()
    except Exception as exc:
        raise config_error(exc) from None


def _find(config: ConnectionsFile, key: str) -> ConnectionConfig:
    """Por id ou nome. NotFoundError se não existe."""
    for conn in config.connections:
        if conn.id == key:
            return conn
    for conn in config.connections:
        if conn.name == key:
            return conn
    raise NotFoundError(f"Conexão não encontrada: {key}")


def _validated_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name or len(name) > 255:
        raise ValidationError("name deve ter de 1 a 255 caracteres")
    return name


def _build(data: dict[str, Any]) -> ConnectionConfig:
    try:
        return ConnectionConfig(**data)
    except ValueError as exc:
        raise ValidationError(f"Conexão inválida: {_errors(exc)}") from None


def _errors(exc: ValueError) -> str:
    """Resumo do erro de validação sem os valores recebidos."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errors())
    return "valores inválidos"


def _test_connection(conn: ConnectionConfig) -> dict[str, Any]:
    """Testa o repositório git (ls-remote) e cronometra. Guarda o resultado em memória."""
    started = time.perf_counter()
    result = ConfigManager.validate_connection(conn)
    latency_ms = int((time.perf_counter() - started) * 1000)
    last = _remember_test(conn.id, result, latency_ms)
    return {k: last[k] for k in ("status", "message", "latency_ms")}


class ConnectionService:
    """Operações sobre as conexões do connections.json."""

    def create(
        self,
        name: str,
        path: str,
        remote_url: str | None = None,
        review_mode: str = "direct",
        enabled: bool = True,
        test: bool = True,
    ) -> Connection:
        """Cria a connection numa pasta local: grava no connections.json e prepara o
        repositório git nela.

        `path` é uma pasta fora do home de dados — já um repositório git (usado como está) ou
        uma pasta comum (`git init` nela, preservando o que já tiver dentro). Com `remote_url`,
        `path` vira o destino do clone. Garante também o workflow de validação de PRs e o
        CODEOWNERS. Com `test=True` e `remote_url`, testa o remoto (`git ls-remote`) antes de
        clonar. A primeira conexão (ou a primeira quando não há padrão) vira a padrão.
        """
        name = _validated_name(name)
        resolved_path = _validated_path(path)
        conn = _build(
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "path": resolved_path,
                "remote_url": remote_url or None,
                "review_mode": review_mode,
                "enabled": enabled,
                "created_at": utcnow(),
            }
        )

        with _json_lock:
            config = _load()
            if any(c.name == name for c in config.connections):
                raise ValidationError(f"Conexão já existe: {name}")
            if any(c.path == resolved_path for c in config.connections):
                raise ValidationError(f"Já existe uma conexão nesse path: {resolved_path}")
            if test and conn.remote_url is not None:
                result = ConfigManager.validate_connection(conn)
                if result["status"] != "ok":
                    raise ValidationError(result["message"])
            self._provision_repo(conn)
            config.connections.append(conn)
            if config.default is None and conn.enabled:
                config.default = conn.id
            ConfigManager.save(config)
        logger.info("Conexão criada: %s", name)
        if test:
            _test_connection(conn)
        return _to_row(conn, config.default)

    @staticmethod
    def _provision_repo(conn: ConnectionConfig) -> None:
        """Clona (ou inicializa) o repositório e garante workflow + CODEOWNERS."""
        repo = GitRepoService(conn.clone_path(), conn.remote_url, conn.review_mode)
        repo.ensure_clone()
        repo.ensure_workflow()
        repo.ensure_codeowners([])

    def list(self) -> list[Connection]:
        """Lista as conexões do connections.json (vazia se não há nenhuma)."""
        config = _load()
        return [_to_row(c, config.default) for c in config.connections]

    def get(self, connection_id: str) -> Connection:
        """Obtém por id (ou nome). NotFoundError se não existe."""
        config = _load()
        return _to_row(_find(config, connection_id), config.default)

    def delete(self, connection_id: str) -> bool:
        """Remove a conexão do connections.json. False se não existe.

        Apagar a padrão passa o posto para outra conexão habilitada (ou deixa sem padrão, se
        não sobrar nenhuma). A pasta do repositório NÃO é apagada: são dados do usuário, e
        removê-los sem confirmação explícita é destrutivo demais para fazer aqui.
        """
        with _json_lock:
            config = _load()
            target = next(
                (c for c in config.connections if connection_id in (c.id, c.name)), None
            )
            if target is None:
                return False
            config.connections = [c for c in config.connections if c.id != target.id]
            if config.default == target.id:
                config.default = next((c.id for c in config.connections if c.enabled), None)
                logger.info("Padrão passou para %s (a anterior foi removida)", config.default)
            ConfigManager.save(config)
        access.forget(target.id)
        _last_tests.pop(target.id, None)
        logger.info("Conexão removida: %s", target.id)
        return True

    def test(self, connection_id: str) -> dict[str, Any]:
        """Testa a conexão (git ls-remote) e guarda o resultado (em memória)."""
        return _test_connection(_find(_load(), connection_id))

    def update(self, connection_id: str, **fields: Any) -> Connection:
        """Atualiza name, is_active (`enabled` no JSON), remote_url e review_mode.

        Os campos ausentes ficam como estão. ValidationError para o resto.
        """
        unknown = set(fields) - set(UPDATABLE_FIELDS)
        if unknown:
            raise ValidationError(f"Campos não editáveis: {', '.join(sorted(unknown))}")
        with _json_lock:
            config = _load()
            old = _find(config, connection_id)
            data = old.model_dump()
            if "name" in fields:
                name = _validated_name(fields["name"])
                if any(c.name == name and c.id != old.id for c in config.connections):
                    raise ValidationError(f"Conexão já existe: {name}")
                data["name"] = name
            if fields.get("is_active") is not None:
                if old.id == config.default and not fields["is_active"]:
                    raise ValidationError("A conexão padrão não pode ser desativada")
                data["enabled"] = bool(fields["is_active"])
            if "remote_url" in fields:
                data["remote_url"] = fields["remote_url"] or None
            if "review_mode" in fields and fields["review_mode"] is not None:
                data["review_mode"] = fields["review_mode"]
            new = _build(data)
            config.connections = [new if c.id == old.id else c for c in config.connections]
            ConfigManager.save(config)
        access.forget(new.id)
        _last_tests.pop(new.id, None)
        return _to_row(new, config.default)

    def health(self) -> list[dict[str, Any]]:
        """Saúde de cada conexão, para o `health_check`: `[{id, name, path, ok,
        parse_errors: [{path, error}]}]`.

        `ok` é falso se a pasta não existe ou não é um repositório git. `parse_errors` são os
        `.md` que a leitura ignorou (frontmatter inválido, id duplicado), do `FileStore`.
        Sem conexão: `[]`.
        """
        rows = []
        for conn in _load().connections:
            root = conn.clone_path()
            exists = root.is_dir()
            errors: list[dict[str, str]] = []
            if exists:
                store = access.store_for(conn)
                errors = [{"path": path, "error": err}
                          for path, err in sorted(store.errors.items())]
            rows.append({"id": conn.id, "name": conn.name, "path": str(root),
                         "ok": exists and (root / ".git").exists(), "parse_errors": errors})
        return rows

    def set_default(self, connection_id: str) -> Connection:
        """Define a padrão do connections.json (vale para a API e para as tools MCP)."""
        with _json_lock:
            config = _load()
            conn = _find(config, connection_id)
            if not conn.enabled:
                raise ValidationError(f"Conexão desabilitada: {conn.name}")
            config.default = conn.id
            ConfigManager.save(config)
        return self.get(conn.id)
