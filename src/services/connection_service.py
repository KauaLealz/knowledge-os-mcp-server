"""Connection service: CRUD e teste de conexões (SQLite, MySQL, PostgreSQL).

O cadastro é o .knowledge/connections.json. A tabela `connections` de cada banco é só o
espelho exigido pela FK de workspaces.
"""

import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.config import ConfigManager, ConnectionConfig, ConnectionsFile
from src.db import session as db_session
from src.db.dialects import detect_type, get_dialect, normalize_url, redact
from src.db.models import DEFAULT_CONNECTION_ID, DEFAULT_CONNECTION_NAME, Connection
from src.exceptions import ConfigError, NotFoundError, ValidationError
from src.services._common import session_scope

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = ("name", "is_active")
_PROBE_TABLE = "_kos_connection_probe"
_DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306}
_json_lock = threading.RLock()  # protege o ciclo carregar -> alterar -> gravar do JSON


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


def _to_row(conn: ConnectionConfig, result: tuple[bool, str, int] | None = None) -> Connection:
    """Connection transiente (fora de qualquer sessão) para serialização. URL sem senha.

    `password_set` é um atributo transiente (não é coluna): diz só se há senha, nunca qual.
    """
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
        last_tested=datetime.utcnow() if result else None,
        test_result=result[1] if result else None,
        created_at=conn.created_at,
    )
    row.password_set = bool(conn.password)  # type: ignore[attr-defined]
    return row


def _load() -> ConnectionsFile:
    try:
        return ConfigManager.load_or_create()
    except Exception as exc:
        raise ConfigError(f"connections.json inválido: {exc}") from None


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


class ConnectionService:
    """Operações sobre connections. A sessão (opcional) é a do catálogo, usada só no default."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def _default_row(self) -> Connection:
        with session_scope(self._session) as s:
            conn = s.get(Connection, DEFAULT_CONNECTION_ID)
            if conn is None:
                raise NotFoundError(f"Conexão não encontrada: {DEFAULT_CONNECTION_ID}")
            return conn

    def create(
        self,
        name: str,
        db_type: str,
        db_url: str,
        test: bool = True,
        password: str | None = None,
    ) -> Connection:
        """Cria a conexão no connections.json. Com test=True testa a URL e sincroniza o schema.

        A senha nunca vai na URL: entra em `password` (uso da UI/API; as tools MCP não a recebem).
        ValidationError se o nome/tipo/URL são inválidos, o nome já existe ou o teste falha.
        """
        name = (name or "").strip()
        if not name or len(name) > 255:
            raise ValidationError("name deve ter de 1 a 255 caracteres")
        if name == DEFAULT_CONNECTION_NAME:
            raise ValidationError(f"Nome reservado: {name}")
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
        try:
            conn = ConnectionConfig(
                id=str(uuid.uuid4()),
                name=name,
                db_type=db_type,
                created_at=datetime.utcnow(),
                **fields,
            )
        except ValueError as exc:
            raise ValidationError(f"Conexão inválida: {exc}") from None
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
        return _to_row(conn, result)

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
        rows = [self._default_row()]
        rows.extend(_to_row(c) for c in _load().connections)
        return rows

    def get(self, connection_id: str) -> Connection:
        """Obtém por id (ou nome). NotFoundError se não existe."""
        if _is_default_row(connection_id):
            return self._default_row()
        return _to_row(_find(_load(), connection_id))

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
        with session_scope(self._session) as s:  # espelho no catálogo (cascata nos workspaces)
            mirror = s.get(Connection, connection_id)
            if mirror is not None:
                s.delete(mirror)
                s.commit()
        db_session._connection_manager.invalidate(connection_id)
        logger.info("Conexão removida: %s", connection_id)
        return True

    def test(self, connection_id: str) -> dict[str, Any]:
        """Testa a conexão. Não levanta por falha de rede."""
        if _is_default_row(connection_id):
            row = self._default_row()
            db_type, url = row.db_type, row.db_url
        else:
            conn = _find(_load(), connection_id)
            db_type, url = conn.db_type, _url_of(conn)
        ok, message, latency = _run_probe(db_type, url)
        return {
            "status": "ok" if ok else "error",
            "message": message,
            "latency_ms": latency,
        }

    def update(self, connection_id: str, **fields: Any) -> Connection:
        """Atualiza name e/ou is_active (`enabled` no JSON). ValidationError para o resto."""
        unknown = set(fields) - set(UPDATABLE_FIELDS)
        if unknown:
            raise ValidationError(f"Campos não editáveis: {', '.join(sorted(unknown))}")
        if connection_id == DEFAULT_CONNECTION_ID:
            raise ValidationError("A conexão default não pode ser alterada")
        with _json_lock:
            config = _load()
            conn = _find(config, connection_id)
            if (name := fields.get("name")) is not None:
                name = name.strip()
                if not name or len(name) > 255 or name == DEFAULT_CONNECTION_NAME:
                    raise ValidationError("name inválido ou reservado")
                if any(c.name == name and c.id != conn.id for c in config.connections):
                    raise ValidationError(f"Conexão já existe: {name}")
                conn.name = name
            if (active := fields.get("is_active")) is not None:
                if conn.id == config.default and not active:
                    raise ValidationError("A conexão default não pode ser desativada")
                conn.enabled = bool(active)
            ConfigManager.save(config)
        db_session._connection_manager.invalidate(conn.id)
        return _to_row(conn)
