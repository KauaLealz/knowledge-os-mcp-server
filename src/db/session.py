"""Engines e sessões SQLAlchemy: catálogo (banco default) + N conexões (multi-DB)."""

import logging
import threading

from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.config import DB_URL
from src.db.dialects import detect_type, get_dialect, redact
from src.db.dialects.base import FTS_COLUMNS, FTS_TABLE
from src.db.dialects.sqlite import create_fts_trigger
from src.db.models import (
    DEFAULT_CONNECTION_ID,
    DEFAULT_CONNECTION_NAME,
    Base,
    Connection,
)
from src.exceptions import DatabaseError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "FTS_COLUMNS",
    "FTS_TABLE",
    "ConnectionManager",
    "close_engine",
    "close_engines",
    "create_db_engine",
    "create_fts_trigger",
    "ensure_connection_row",
    "get_engine",
    "get_session",
    "init_db",
]


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


def redact_url(url: str) -> str:
    """URL com a senha mascarada."""
    from sqlalchemy.engine import make_url

    return make_url(url).render_as_string(hide_password=True)


def _migrate_legacy_workspaces(engine: Engine) -> None:
    """Bancos SQLite anteriores ao T7 não têm workspaces.connection_id: adiciona a coluna."""
    inspector = inspect(engine)
    if "workspaces" not in inspector.get_table_names():
        return
    if "connection_id" in {c["name"] for c in inspector.get_columns("workspaces")}:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE workspaces ADD COLUMN connection_id VARCHAR(36) "
                f"NOT NULL DEFAULT '{DEFAULT_CONNECTION_ID}'"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_workspace_connection ON workspaces(connection_id)")
        )
    logger.info("workspaces.connection_id adicionada ao banco legado")


def init_db(
    engine: Engine | None = None,
    connection_id: str = DEFAULT_CONNECTION_ID,
    connection_name: str = DEFAULT_CONNECTION_NAME,
) -> Engine:
    """Inicializa o banco: tabelas, busca textual do dialect e linha de connection.

    Idempotente. Para bancos de conexões externas, `connection_id` / `connection_name`
    identificam a linha espelhada em `connections` (exigida pela FK de workspaces).
    """
    engine = engine or create_db_engine()
    try:
        Base.metadata.create_all(bind=engine)
        if engine.dialect.name == "sqlite":
            _migrate_legacy_workspaces(engine)
        get_dialect(engine.dialect.name).create_fts_table(engine)
        ensure_connection_row(engine, connection_id, connection_name)
    except SQLAlchemyError as exc:
        raise DatabaseError(f"Falha ao inicializar o banco: {exc}") from exc
    logger.debug("Banco inicializado")
    return engine


class ConnectionManager:
    """Mantém um Engine por connection_id. O banco default (catálogo) guarda as Connections."""

    def __init__(self, default_engine: Engine | None = None) -> None:
        self._engines: dict[str, Engine] = {}
        self._lock = threading.RLock()
        if default_engine is not None:
            self._engines[DEFAULT_CONNECTION_ID] = default_engine

    def _default(self) -> Engine:
        if DEFAULT_CONNECTION_ID not in self._engines:
            self._engines[DEFAULT_CONNECTION_ID] = init_db()
        return self._engines[DEFAULT_CONNECTION_ID]

    def get_engine(self, connection_id: str | None = None) -> Engine:
        """Engine da conexão (cria e inicializa no primeiro uso). None = banco default."""
        cid = connection_id or DEFAULT_CONNECTION_ID
        with self._lock:
            if cid == DEFAULT_CONNECTION_ID:
                return self._default()
            if cid not in self._engines:
                self._engines[cid] = self._open(cid)
            return self._engines[cid]

    def _open(self, connection_id: str) -> Engine:
        with Session(self._default()) as s:
            conn = s.get(Connection, connection_id)
            if conn is None:
                raise NotFoundError(f"Conexão não encontrada: {connection_id}")
            if not conn.is_active:
                raise ValidationError(f"Conexão inativa: {conn.name}")
            db_type, db_url, name = conn.db_type, conn.db_url, conn.name
        engine = get_dialect(db_type).create_engine(db_url)
        try:
            init_db(engine, connection_id=connection_id, connection_name=name)
            from src.db.migrations import bootstrap_labels  # import tardio: evita ciclo

            with Session(engine) as s:
                bootstrap_labels(s)
        except Exception as exc:
            engine.dispose()
            raise DatabaseError(
                f"Falha ao abrir a conexão {name!r}: {redact(str(exc), db_url)}"
            ) from None
        return engine

    def get_session(self, connection_id: str | None = None) -> Session:
        engine = self.get_engine(connection_id)
        return sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    def invalidate(self, connection_id: str) -> None:
        """Descarta o engine em cache (conexão removida, desativada ou alterada)."""
        if connection_id == DEFAULT_CONNECTION_ID:
            return
        with self._lock:
            engine = self._engines.pop(connection_id, None)
        if engine is not None:
            engine.dispose()

    def close_all(self) -> None:
        with self._lock:
            engines, self._engines = list(self._engines.values()), {}
        for engine in engines:
            engine.dispose()


_connection_manager = ConnectionManager()


def get_engine(connection_id: str | None = None) -> Engine:
    """Engine da conexão informada; sem argumento, o banco default (inicializado no 1º uso)."""
    return _connection_manager.get_engine(connection_id)


def get_session(target: Engine | str | None = None) -> Session:
    """Nova sessão. `target` pode ser um Engine ou um connection_id (None = default)."""
    if isinstance(target, Engine):
        return sessionmaker(autocommit=False, autoflush=False, bind=target)()
    return _connection_manager.get_session(target)


def close_engines() -> None:
    """Fecha todos os engines (default e conexões)."""
    _connection_manager.close_all()


def close_engine() -> None:
    """Compatibilidade T1-T5: fecha os engines."""
    close_engines()
