"""Connection service: CRUD e teste de conexões (SQLite, MySQL, PostgreSQL).

O cadastro é o connections.json do home. A tabela `connections` de cada banco é só o
espelho exigido pela FK de workspaces. A senha é só de escrita: nada aqui a devolve.
"""

import logging
import threading
import time
import uuid
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.config import (
    CATALOG_ID,
    ConfigManager,
    ConnectionConfig,
    ConnectionsFile,
    config_error,
)
from src.db import session as db_session
from src.db.dialects import detect_type, get_dialect, normalize_url, redact
from src.db.models import DEFAULT_CONNECTION_ID, DEFAULT_CONNECTION_NAME, Connection
from src.db.schema_sync import schema_sync
from src.db.timeutil import utcnow
from src.exceptions import NotFoundError, ValidationError
from src.services._common import session_scope

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = (
    "name", "is_active", "path", "host", "port", "database", "username", "password",
)
_SERVER_FIELDS = ("host", "port", "database", "username", "password")
# Mudar o destino com a senha guardada a enviaria a outro servidor: exige senha de novo.
_DESTINATION_FIELDS = ("path", "host", "port", "database", "username")
_HOST_FORBIDDEN = set("@/?# \t\r\n\\")
_PROBE_TABLE = "_kos_connection_probe"
_DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306}
_json_lock = threading.RLock()  # protege o ciclo carregar -> alterar -> gravar do JSON
# Último teste de cada conexão: só em memória, por processo (some ao reiniciar).
_last_tests: dict[str, dict[str, Any]] = {}


def _probe(engine: Engine) -> None:
    """Conecta, cria uma tabela dummy e a remove."""
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {_PROBE_TABLE} (id INTEGER)"))
        conn.execute(text(f"DROP TABLE {_PROBE_TABLE}"))


def _run_probe(db_type: str, url: str) -> tuple[bool, str, int]:
    """Testa a URL com um engine descartável. Retorna (ok, mensagem, latência_ms)."""
    started = time.perf_counter()
    engine: Engine | None = None
    try:
        engine = get_dialect(db_type).create_engine(url)
        _probe(engine)
        ok, message = True, "connected"
    except SQLAlchemyError as exc:
        ok, message = False, f"connection failed: {redact(str(exc.orig or exc), url)}"
    except Exception as exc:  # driver ausente, URL malformada etc.
        ok, message = False, f"connection failed: {redact(str(exc), url)}"
    finally:
        if engine is not None:
            engine.dispose()
    latency = int((time.perf_counter() - started) * 1000)
    return ok, message[:500], latency


def _url_of(conn: ConnectionConfig) -> str:
    return normalize_url(conn.get_url())


def _remember_test(connection_id: str, result: tuple[bool, str, int]) -> dict[str, Any]:
    last = {
        "status": "ok" if result[0] else "error",
        "message": result[1],
        "latency_ms": result[2],
        "tested_at": utcnow(),
    }
    _last_tests[connection_id] = last
    return last


def _decorate(
    row: Connection, default_id: str, *, path: str | None, password_set: bool
) -> Connection:
    """Atributos transientes (não são colunas). `password_set` diz só se há senha."""
    last = _last_tests.get(row.id)
    row.last_tested = last["tested_at"] if last else None
    row.test_result = last["message"] if last else None
    row.password_set = password_set  # type: ignore[attr-defined]
    row.path = path  # type: ignore[attr-defined]
    row.is_default = row.id == default_id  # type: ignore[attr-defined]
    row.last_test = last  # type: ignore[attr-defined]
    return row


def _to_row(
    conn: ConnectionConfig, default_id: str, result: tuple[bool, str, int] | None = None
) -> Connection:
    """Connection transiente (fora de qualquer sessão) para serialização. URL sem senha."""
    row = Connection(
        id=conn.id,
        name=conn.name,
        db_type=conn.db_type,
        db_url=db_session.redact_url(_url_of(conn)),
        host=conn.host,
        port=conn.port,
        database=conn.database,
        username=conn.username,
        is_active=conn.enabled,
        created_at=conn.created_at,
    )
    if result:
        _remember_test(conn.id, result)
    return _decorate(row, default_id, path=conn.path, password_set=bool(conn.password))


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


def _clean(value: Any) -> Any:
    """Strings aparadas; vazio vira None."""
    if isinstance(value, str):
        return value.strip() or None
    return value


def _check_shape(conn: ConnectionConfig) -> None:
    """Campos coerentes com o tipo. As mensagens nunca ecoam valores (podem ser sensíveis)."""
    if conn.db_type == "sqlite":
        extra = [f for f in _SERVER_FIELDS if getattr(conn, f) is not None]
        if extra:
            raise ValidationError(f"Campos que não se aplicam ao SQLite: {', '.join(extra)}")
        if not conn.path or conn.path == ":memory:":
            raise ValidationError("A conexão SQLite precisa de um path de arquivo")
        if "://" in conn.path:
            raise ValidationError("path deve ser um caminho de arquivo, não uma URL")
        return
    if conn.path is not None:
        raise ValidationError("path só se aplica ao SQLite")
    if not conn.host:
        raise ValidationError("host é obrigatório")
    if any(ch in _HOST_FORBIDDEN for ch in conn.host):
        raise ValidationError("host inválido: informe só o nome do servidor, sem URL ou senha")
    if not conn.database:
        raise ValidationError("database é obrigatório")


def _validated_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name or len(name) > 255:
        raise ValidationError("name deve ter de 1 a 255 caracteres")
    if name == DEFAULT_CONNECTION_NAME:
        raise ValidationError(f"Nome reservado: {name}")
    return name


def _build(data: dict[str, Any]) -> ConnectionConfig:
    """ConnectionConfig validada (tipo, porta, coerência dos campos)."""
    try:
        conn = ConnectionConfig(**data)
    except ValueError as exc:
        raise ValidationError(f"Conexão inválida: {_errors(exc)}") from None
    _check_shape(conn)
    return conn


def _errors(exc: ValueError) -> str:
    """Resumo do erro de validação sem os valores recebidos (a senha pode estar entre eles)."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errors()
        )
    return "valores inválidos"


class ConnectionService:
    """Operações sobre connections. A sessão (opcional) é a do catálogo, usada só no default."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def _default_row(self, default_id: str) -> Connection:
        with session_scope(self._session, DEFAULT_CONNECTION_ID) as s:
            conn = s.get(Connection, DEFAULT_CONNECTION_ID)
            if conn is None:
                raise NotFoundError(f"Conexão não encontrada: {DEFAULT_CONNECTION_ID}")
            path = make_url(conn.db_url).database if conn.db_type == "sqlite" else None
            # cópia transiente: decorar a linha da sessão a sujaria (last_tested é coluna)
            row = Connection(
                id=conn.id, name=conn.name, db_type=conn.db_type, db_url=conn.db_url,
                host=conn.host, port=conn.port, database=conn.database,
                username=conn.username, is_active=conn.is_active, created_at=conn.created_at,
                updated_at=conn.updated_at,
            )
            return _decorate(row, default_id, path=path, password_set=False)

    def create(
        self,
        name: str,
        db_type: str,
        db_url: str,
        test: bool = True,
        password: str | None = None,
    ) -> Connection:
        """Cria a conexão a partir de uma URL (uso das tools MCP). Com test=True testa e sincroniza.

        A senha nunca vai na URL: entra em `password` (as tools MCP não a recebem).
        """
        get_dialect(db_type)  # valida o tipo
        if detect_type(db_url) != db_type:
            raise ValidationError(f"A URL não é de um banco {db_type}")
        parsed = make_url(normalize_url(db_url))
        if parsed.password:
            raise ValidationError(
                "A URL não pode conter senha: informe-a no campo password "
                "(pela UI ou editando o connections.json)"
            )
        if db_type == "sqlite":
            if not parsed.database or parsed.database == ":memory:":
                raise ValidationError("A URL SQLite precisa de um caminho de arquivo")
            fields: dict[str, Any] = {"path": parsed.database}
        else:
            if not parsed.database:
                raise ValidationError("A URL precisa do nome do banco")
            fields = {
                "host": parsed.host or "localhost",
                "port": parsed.port or _DEFAULT_PORTS[db_type],
                "database": parsed.database,
                "username": parsed.username,
                "password": password or None,
            }
        return self.add(name, db_type, test=test, **fields)

    def add(
        self,
        name: str,
        db_type: str,
        *,
        test: bool = False,
        enabled: bool = True,
        **fields: Any,
    ) -> Connection:
        """Cria a conexão com campos estruturados (path | host, port, database, ...).

        Sem `test` só grava (nada de rede): o teste é um passo à parte. ValidationError se
        os campos são inválidos, o nome já existe ou (com test) o teste falha.
        """
        name = _validated_name(name)
        get_dialect(db_type)
        unknown = set(fields) - {"path", *_SERVER_FIELDS}
        if unknown:
            raise ValidationError(f"Campos desconhecidos: {', '.join(sorted(unknown))}")
        data = {k: _clean(v) if k != "password" else (v or None) for k, v in fields.items()}
        if db_type != "sqlite" and data.get("port") is None:
            data["port"] = _DEFAULT_PORTS[db_type]
        conn = _build(
            {
                **data,
                "id": str(uuid.uuid4()),
                "name": name,
                "db_type": db_type,
                "enabled": enabled,
                "created_at": utcnow(),
            }
        )
        url = _url_of(conn)

        result: tuple[bool, str, int] | None = None
        with _json_lock:
            config = _load()
            if any(c.name == name for c in config.connections):
                raise ValidationError(f"Conexão já existe: {name}")
            if test:
                result = _run_probe(db_type, url)
                if not result[0]:
                    raise ValidationError(result[1])
                self._sync_schema(conn, url)
            config.connections.append(conn)
            ConfigManager.save(config)
        logger.info("Conexão criada: %s (%s)", name, db_type)
        return _to_row(conn, config.default, result)

    @staticmethod
    def _sync_schema(conn: ConnectionConfig, url: str) -> None:
        """Cria o schema que falta no banco da conexão (a mesma rotina do primeiro uso)."""
        engine = get_dialect(conn.db_type).create_engine(url)
        try:
            db_session.init_db(engine, connection_id=conn.id, connection_name=conn.name)
        except Exception as exc:
            raise ValidationError(
                f"Falha ao sincronizar o schema: {redact(str(exc), url)}"
            ) from None
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

        Retorna False se não existe. Dados que vivem no banco da conexão não são tocados.
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
        """Testa a conexão e guarda o resultado (em memória). Não levanta por falha de rede."""
        if _is_default_row(connection_id):
            key = DEFAULT_CONNECTION_ID
            # engine vivo (como em sync_schema): a db_url do espelho pode estar defasada
            db_type = self._default_row(_load().default).db_type
            url = db_session.get_engine(DEFAULT_CONNECTION_ID).url.render_as_string(
                hide_password=False
            )
        else:
            conn = _find(_load(), connection_id)
            key, db_type, url = conn.id, conn.db_type, _url_of(conn)
        result = _run_probe(db_type, url)
        last = _remember_test(key, result)
        return {k: last[k] for k in ("status", "message", "latency_ms")}

    def update(self, connection_id: str, **fields: Any) -> Connection:
        """Atualiza name, is_active (`enabled` no JSON) e os campos de conexão.

        Os campos ausentes ficam como estão; `password=None` limpa a senha e um valor novo a
        substitui. ValidationError para o resto (o tipo não muda).
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
            for key in ("path", "host", "port", "database", "username"):
                if key in fields:
                    data[key] = _clean(fields[key])
            if "password" in fields:
                data["password"] = fields["password"] or None
            if old.db_type != "sqlite" and data.get("port") is None:
                data["port"] = _DEFAULT_PORTS[old.db_type]
            new = _build(data)
            if (
                old.password
                and "password" not in fields
                and any(getattr(new, k) != getattr(old, k) for k in _DESTINATION_FIELDS)
            ):
                raise ValidationError(
                    "Informe a senha de novo ao mudar host, porta, banco ou usuário"
                )
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
        """Sincroniza o schema do banco da conexão (ou só lista, com dry_run). Inclui o catálogo."""
        if _is_default_row(connection_id):
            key, db_type, name = DEFAULT_CONNECTION_ID, "sqlite", DEFAULT_CONNECTION_NAME
            url = db_session.get_engine(DEFAULT_CONNECTION_ID).url.render_as_string(
                hide_password=False
            )
        else:
            conn = _find(_load(), connection_id)
            key, db_type, name, url = conn.id, conn.db_type, conn.name, _url_of(conn)
        engine = get_dialect(db_type).create_engine(url)
        try:
            if not dry_run and db_type == "postgresql":
                with engine.begin() as c:
                    c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            result = schema_sync(engine, dry_run=dry_run)
            if not dry_run and not result["pending_manual"]:
                db_session.ensure_connection_row(engine, key, name)
        except Exception as exc:
            raise ValidationError(
                f"Falha ao sincronizar o schema: {redact(str(exc), url)}"[:500]
            ) from None
        finally:
            engine.dispose()
        if not dry_run:
            db_session._connection_manager.invalidate(key)
        return {"connection_id": key, **result}
