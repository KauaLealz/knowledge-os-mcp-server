"""Connection service: CRUD e teste de conexões (um repositório git por connection).

O cadastro é o connections.json do home. A tabela `connections` de cada banco é só o
espelho exigido pela FK de workspaces. O índice de busca (SQLite) e o clone git vivem
no home de dados, um por connection, derivados do id (`ConnectionConfig.clone_path`/
`index_url`).
"""

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from knowledge_os.config import (
    CATALOG_ID,
    ConfigManager,
    ConnectionConfig,
    ConnectionsFile,
    config_error,
)
from knowledge_os.db import session as db_session
from knowledge_os.db.models import DEFAULT_CONNECTION_ID, DEFAULT_CONNECTION_NAME, Connection
from knowledge_os.db.schema_sync import schema_sync
from knowledge_os.db.timeutil import utcnow
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import refuse_home_source, session_scope
from knowledge_os.services.git_repo_service import GitRepoService

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


def _decorate(
    row: Connection,
    default_id: str,
    *,
    remote_url: str | None,
    review_mode: str,
    path: str | None = None,
) -> Connection:
    """Atributos transientes (não são colunas): git, não banco."""
    last = _last_tests.get(row.id)
    row.last_tested = last["tested_at"] if last else None
    row.test_result = last["message"] if last else None
    row.remote_url = remote_url  # type: ignore[attr-defined]
    row.review_mode = review_mode  # type: ignore[attr-defined]
    row.path = path  # type: ignore[attr-defined]
    row.is_default = row.id == default_id  # type: ignore[attr-defined]
    row.last_test = last  # type: ignore[attr-defined]
    return row


def _to_row(conn: ConnectionConfig, default_id: str) -> Connection:
    """Connection transiente (fora de qualquer sessão) para serialização."""
    row = Connection(
        id=conn.id,
        name=conn.name,
        db_type="sqlite",
        db_url=db_session.redact_url(conn.index_url()),
        is_active=conn.enabled,
        created_at=conn.created_at,
    )
    return _decorate(
        row, default_id, remote_url=conn.remote_url, review_mode=conn.review_mode, path=conn.path
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
        return ConfigManager.load_or_create()
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


def _is_default_row(key: str) -> bool:
    return key in (DEFAULT_CONNECTION_ID, DEFAULT_CONNECTION_NAME)


def _validated_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name or len(name) > 255:
        raise ValidationError("name deve ter de 1 a 255 caracteres")
    if name == DEFAULT_CONNECTION_NAME:
        raise ValidationError(f"Nome reservado: {name}")
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
    """Operações sobre connections. A sessão (opcional) é a do catálogo, usada só no default."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def _default_row(self, default_id: str) -> Connection:
        with session_scope(self._session, DEFAULT_CONNECTION_ID) as s:
            conn = s.get(Connection, DEFAULT_CONNECTION_ID)
            if conn is None:
                raise NotFoundError(f"Conexão não encontrada: {DEFAULT_CONNECTION_ID}")
            # cópia transiente: decorar a linha da sessão a sujaria (last_tested é coluna)
            row = Connection(
                id=conn.id,
                name=conn.name,
                db_type=conn.db_type,
                db_url=conn.db_url,
                is_active=conn.is_active,
                created_at=conn.created_at,
                updated_at=conn.updated_at,
            )
            return _decorate(row, default_id, remote_url=None, review_mode="direct")

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

        `path` é uma pasta existente, fora do home de dados — já um repositório git (usado
        como está) ou uma pasta comum (`git init` nela, preservando o que já tiver dentro).
        Com `remote_url`, `path` vira o destino do clone. Garante também o workflow de
        validação de PRs e o CODEOWNERS (sem regras ainda — trabalho futuro). Com
        `test=True` e `remote_url`, testa o remoto (`git ls-remote`) antes de clonar.
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
            self._sync_schema(conn)
            config.connections.append(conn)
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

    @staticmethod
    def _sync_schema(conn: ConnectionConfig) -> None:
        """Cria o schema que falta no índice SQLite da connection (a mesma rotina do 1º uso)."""
        from knowledge_os.db.dialects import get_dialect

        engine = get_dialect("sqlite").create_engine(conn.index_url())
        try:
            db_session.init_db(engine, connection_id=conn.id, connection_name=conn.name)
        except Exception as exc:
            raise ValidationError(f"Falha ao sincronizar o schema: {exc}") from None
        finally:
            engine.dispose()

    def list(self) -> list[Connection]:
        """Lista as conexões: a "default" (catálogo) primeiro, depois as do JSON."""
        config = _load()
        rows = [self._default_row(config.default)]
        rows.extend(_to_row(c, config.default) for c in config.connections)
        return rows

    def get(self, connection_id: str) -> Connection:
        """Obtém por id (ou nome). NotFoundError se não existe."""
        config = _load()
        if _is_default_row(connection_id):
            return self._default_row(config.default)
        return _to_row(_find(config, connection_id), config.default)

    def delete(self, connection_id: str) -> bool:
        """Remove a conexão do JSON e os workspaces do catálogo ligados a ela.

        Retorna False se não existe. O clone git e o índice SQLite NÃO são apagados:
        são dados do usuário, e removê-los sem confirmação explícita é destrutivo
        demais para fazer aqui — fica para uma limpeza manual ou um comando à parte.
        """
        if connection_id == DEFAULT_CONNECTION_ID:
            raise ValidationError("A conexão default não pode ser removida")
        with _json_lock:
            config = _load()
            if connection_id not in [c.id for c in config.connections]:
                return False
            if connection_id == config.default:
                raise ValidationError("A conexão default não pode ser removida")
            config.connections = [c for c in config.connections if c.id != connection_id]
            ConfigManager.save(config)
        with session_scope(self._session, DEFAULT_CONNECTION_ID) as s:  # espelho no catálogo
            mirror = s.get(Connection, connection_id)
            if mirror is not None:
                s.delete(mirror)
                s.commit()
        db_session._connection_manager.invalidate(connection_id)
        _last_tests.pop(connection_id, None)
        logger.info("Conexão removida: %s", connection_id)
        return True

    def test(self, connection_id: str) -> dict[str, Any]:
        """Testa a conexão (git ls-remote) e guarda o resultado (em memória).

        O catálogo é sempre local (sem `remote_url`): não há o que testar.
        """
        if _is_default_row(connection_id):
            result = {"status": "ok", "message": "Repositório local (sem remote)"}
            last = _remember_test(DEFAULT_CONNECTION_ID, result, 0)
            return {k: last[k] for k in ("status", "message", "latency_ms")}
        conn = _find(_load(), connection_id)
        return _test_connection(conn)

    def update(self, connection_id: str, **fields: Any) -> Connection:
        """Atualiza name, is_active (`enabled` no JSON), remote_url e review_mode.

        Os campos ausentes ficam como estão. ValidationError para o resto.
        """
        unknown = set(fields) - set(UPDATABLE_FIELDS)
        if unknown:
            raise ValidationError(f"Campos não editáveis: {', '.join(sorted(unknown))}")
        if _is_default_row(connection_id):
            raise ValidationError("A conexão default não pode ser alterada")
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
                    raise ValidationError("A conexão default não pode ser desativada")
                data["enabled"] = bool(fields["is_active"])
            if "remote_url" in fields:
                data["remote_url"] = fields["remote_url"] or None
            if "review_mode" in fields and fields["review_mode"] is not None:
                data["review_mode"] = fields["review_mode"]
            new = _build(data)
            config.connections = [new if c.id == old.id else c for c in config.connections]
            ConfigManager.save(config)
        db_session._connection_manager.invalidate(new.id)
        _last_tests.pop(new.id, None)
        return _to_row(new, config.default)

    def set_default(self, connection_id: str) -> Connection:
        """Define o default do connections.json (vale para a API e para as tools MCP)."""
        with _json_lock:
            config = _load()
            if _is_default_row(connection_id):
                target = CATALOG_ID
            else:
                conn = _find(config, connection_id)
                if not conn.enabled:
                    raise ValidationError(f"Conexão desabilitada: {conn.name}")
                target = conn.id
            config.default = target
            ConfigManager.save(config)
        return self.get(target)

    def sync_schema(self, connection_id: str, dry_run: bool = True) -> dict[str, Any]:
        """Sincroniza o schema do índice SQLite da conexão (ou só lista, com dry_run)."""
        if _is_default_row(connection_id):
            key, name = DEFAULT_CONNECTION_ID, DEFAULT_CONNECTION_NAME
            url = db_session.get_engine(DEFAULT_CONNECTION_ID).url.render_as_string(
                hide_password=False
            )
        else:
            conn = _find(_load(), connection_id)
            key, name, url = conn.id, conn.name, conn.index_url()
        from knowledge_os.db.dialects import get_dialect

        engine = get_dialect("sqlite").create_engine(url)
        try:
            result = schema_sync(engine, dry_run=dry_run)
            if not dry_run and not result["pending_manual"]:
                db_session.ensure_connection_row(engine, key, name)
        except Exception as exc:
            raise ValidationError(f"Falha ao sincronizar o schema: {exc}"[:500]) from None
        finally:
            engine.dispose()
        if not dry_run:
            db_session._connection_manager.invalidate(key)
        return {"connection_id": key, **result}
