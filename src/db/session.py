"""Engines e sessões SQLAlchemy: catálogo (banco default) + N conexões (multi-DB)."""

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.config import DB_URL, ConfigManager, ConnectionConfig, config_error
from src.db.dialects import detect_type, get_dialect, redact
from src.db.dialects.base import FTS_COLUMNS, FTS_TABLE
from src.db.dialects.sqlite import create_fts_trigger
from src.db.models import (
    DEFAULT_CONNECTION_ID,
    DEFAULT_CONNECTION_NAME,
    Connection,
)
from src.db.schema_sync import schema_sync
from src.exceptions import DatabaseError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRY_BUDGET_S = 10.0  # teto total de espera em retentativas
RETRY_FIRST_WAIT_S = 0.05  # primeira espera; dobra a cada tentativa (teto de 1 s)
_LOCK_MARKERS = ("database is locked", "database table is locked", "busy")

__all__ = [
    "FTS_COLUMNS",
    "FTS_TABLE",
    "ConnectionManager",
    "close_engine",
    "close_engines",
    "create_db_engine",
    "create_fts_trigger",
    "check_connection",
    "connection_id_of",
    "default_connection_id",
    "ensure_connection_row",
    "get_engine",
    "get_session",
    "init_db",
    "run_with_retry",
]


def is_lock_error(exc: BaseException) -> bool:
    """OperationalError de trava (SQLite: "database is locked" / "busy")."""
    return isinstance(exc, OperationalError) and any(
        m in str(exc.orig if exc.orig is not None else exc).lower() for m in _LOCK_MARKERS
    )


def run_with_retry(work: Callable[[], T], *, retry_conflict: bool = False) -> T:
    """Reexecuta a unidade de trabalho inteira enquanto o banco estiver travado.

    Espera crescente até `RETRY_BUDGET_S`; no fim converte para DatabaseError legível.
    `work` deve abrir e fechar a própria sessão (cada tentativa recomeça do zero). Com
    `retry_conflict`, uma IntegrityError também reexecuta (outro processo criou a mesma
    linha primeiro: na nova tentativa ela já existe).
    """
    deadline = time.monotonic() + RETRY_BUDGET_S
    wait = RETRY_FIRST_WAIT_S
    attempts = 0
    while True:
        attempts += 1
        try:
            return work()
        except OperationalError as exc:
            if not is_lock_error(exc):
                raise
            last: Exception = exc
        except IntegrityError as exc:
            if not retry_conflict or attempts >= 5:
                raise
            last = exc
        if time.monotonic() + wait > deadline:
            if isinstance(last, IntegrityError):
                raise last
            raise DatabaseError(
                "Banco ocupado por outro processo: a gravação não conseguiu a trava a tempo. "
                "Tente de novo em instantes."
            ) from last
        logger.debug("Banco ocupado, nova tentativa em %.2fs", wait)
        time.sleep(wait)
        wait = min(wait * 2, 1.0)


def create_db_engine(url: str = DB_URL) -> Engine:
    """Cria o engine do dialect detectado na URL (SQLite com WAL por padrão)."""
    return get_dialect(detect_type(url)).create_engine(url)


def ensure_connection_row(
    engine: Engine,
    connection_id: str = DEFAULT_CONNECTION_ID,
    name: str = DEFAULT_CONNECTION_NAME,
    db_type: str | None = None,
    db_url: str | None = None,
) -> None:
    """Garante a linha de `connections` que a FK de workspaces exige neste banco.

    A URL gravada nunca contém a senha.
    """
    safe_url = db_url if db_url is not None else engine.url.render_as_string(hide_password=True)
    with Session(engine) as s:
        if s.get(Connection, connection_id) is None:
            s.add(
                Connection(
                    id=connection_id,
                    name=name,
                    db_type=db_type or engine.dialect.name,
                    db_url=redact_url(safe_url),
                )
            )
            s.commit()


def default_connection_id() -> str:
    """Id da conexão default do connections.json (relido a cada chamada); "default" = catálogo."""
    try:
        return ConfigManager.load_or_create().default
    except Exception as exc:
        raise config_error(exc) from None


def check_connection(connection_id: str) -> None:
    """NotFoundError se a conexão não existe; ValidationError se está desabilitada."""
    if connection_id != DEFAULT_CONNECTION_ID:
        ConnectionManager._resolve(connection_id)


def connection_id_of(engine: Engine) -> str | None:
    """Id da conexão dona do engine, se ele veio do ConnectionManager (senão None)."""
    return _connection_manager.id_of(engine)


def redact_url(url: str) -> str:
    """URL com a senha mascarada."""
    from sqlalchemy.engine import make_url

    return make_url(url).render_as_string(hide_password=True)


def init_db(
    engine: Engine | None = None,
    connection_id: str = DEFAULT_CONNECTION_ID,
    connection_name: str = DEFAULT_CONNECTION_NAME,
) -> Engine:
    """Inicializa o banco: sincroniza o schema (schema_sync) e garante a linha de connection.

    Idempotente. Para bancos de conexões externas, `connection_id` / `connection_name`
    identificam a linha espelhada em `connections` (exigida pela FK de workspaces).
    """
    engine = engine or create_db_engine()
    try:
        result = schema_sync(engine)
        if result["pending_manual"]:
            logger.warning("Schema com diferenças manuais: %s", result["pending_manual"])
        ensure_connection_row(engine, connection_id, connection_name)
    except SQLAlchemyError as exc:
        raise DatabaseError(f"Falha ao inicializar o banco: {exc}") from exc
    logger.debug("Banco inicializado")
    return engine


class ConnectionManager:
    """Um Engine por connection_id. Cadastro: connections.json; o default é o catálogo."""

    def __init__(self, default_engine: Engine | None = None) -> None:
        self._engines: dict[str, Engine] = {}
        self._urls: dict[str, str] = {}
        self._lock = threading.RLock()
        if default_engine is not None:
            self._engines[DEFAULT_CONNECTION_ID] = default_engine

    def _default(self) -> Engine:
        if DEFAULT_CONNECTION_ID not in self._engines:
            self._engines[DEFAULT_CONNECTION_ID] = init_db()
        return self._engines[DEFAULT_CONNECTION_ID]

    def get_engine(self, connection_id: str | None = None) -> Engine:
        """Engine da conexão (cria e inicializa no primeiro uso). None = default do JSON.

        O connections.json é relido a cada chamada: o engine em cache é descartado se a
        conexão foi removida, desabilitada ou teve a URL alterada.
        """
        cid = connection_id or default_connection_id()
        with self._lock:
            if cid == DEFAULT_CONNECTION_ID:
                return self._default()
            try:
                conn = self._resolve(cid)
            except (NotFoundError, ValidationError):
                self.invalidate(cid)
                raise
            url = conn.get_url()
            if cid in self._engines and self._urls.get(cid) == url:
                return self._engines[cid]
            self.invalidate(cid)
            self._engines[cid] = self._open(cid, conn)
            self._urls[cid] = url
            return self._engines[cid]

    @staticmethod
    def _resolve(connection_id: str) -> ConnectionConfig:
        """Conexão habilitada do connections.json (a única fonte de cadastro)."""
        try:
            config = ConfigManager.load_or_create()
        except Exception as exc:
            raise config_error(exc) from None
        try:
            conn = config.get_connection(connection_id)
        except ValueError:
            raise NotFoundError(f"Conexão não encontrada: {connection_id}") from None
        if not conn.enabled:
            raise ValidationError(f"Conexão inativa: {conn.name}")
        return conn

    def _open(self, connection_id: str, conn: ConnectionConfig | None = None) -> Engine:
        conn = conn or self._resolve(connection_id)
        url = conn.get_url()
        engine = get_dialect(conn.db_type).create_engine(url)
        try:
            init_db(engine, connection_id=connection_id, connection_name=conn.name)
            from src.db.migrations import bootstrap_labels  # import tardio: evita ciclo

            with Session(engine) as s:
                bootstrap_labels(s)
        except Exception as exc:
            engine.dispose()
            raise DatabaseError(
                f"Falha ao abrir a conexão {conn.name!r}: {redact(str(exc), url)}"
            ) from None
        return engine

    def id_of(self, engine: Engine) -> str | None:
        with self._lock:
            for cid, known in self._engines.items():
                if known is engine:
                    return cid
        return None

    def get_session(self, connection_id: str | None = None) -> Session:
        engine = self.get_engine(connection_id)
        return sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    def invalidate(self, connection_id: str) -> None:
        """Descarta o engine em cache (conexão removida, desativada ou alterada)."""
        if connection_id == DEFAULT_CONNECTION_ID:
            return
        with self._lock:
            engine = self._engines.pop(connection_id, None)
            self._urls.pop(connection_id, None)
        if engine is not None:
            engine.dispose()

    def close_all(self) -> None:
        with self._lock:
            engines, self._engines = list(self._engines.values()), {}
            self._urls = {}
        for engine in engines:
            engine.dispose()


_connection_manager = ConnectionManager()


def get_engine(connection_id: str | None = None) -> Engine:
    """Engine da conexão informada; sem argumento, o da conexão default do connections.json."""
    return _connection_manager.get_engine(connection_id)


def get_session(target: Engine | str | None = None) -> Session:
    """Nova sessão. `target` pode ser um Engine ou um connection_id (None = default do JSON)."""
    if isinstance(target, Engine):
        return sessionmaker(autocommit=False, autoflush=False, bind=target)()
    return _connection_manager.get_session(target)


def close_engines() -> None:
    """Fecha todos os engines (default e conexões)."""
    _connection_manager.close_all()


def close_engine() -> None:
    """Compatibilidade T1-T5: fecha os engines."""
    close_engines()
