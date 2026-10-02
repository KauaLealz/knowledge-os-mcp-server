"""Connection service: CRUD e teste de conexões a bancos (SQLite, MySQL, PostgreSQL)."""

import logging
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from src.db import session as db_session
from src.db.dialects import detect_type, get_dialect, normalize_url, redact
from src.db.models import DEFAULT_CONNECTION_ID, DEFAULT_CONNECTION_NAME, Connection
from src.exceptions import NotFoundError, ValidationError
from src.services._common import session_scope

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = ("name", "is_active")
_PROBE_TABLE = "_kos_connection_probe"


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


class ConnectionService:
    """Operações sobre connections. Elas vivem no banco default (catálogo)."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def _get(self, s: Session, connection_id: str) -> Connection:
        conn = s.get(Connection, connection_id)
        if conn is None:
            conn = s.scalar(select(Connection).where(Connection.name == connection_id))
        if conn is None:
            raise NotFoundError(f"Conexão não encontrada: {connection_id}")
        return conn

    def create(self, name: str, db_type: str, db_url: str, test: bool = True) -> Connection:
        """Cria a conexão. Com test=True a URL é testada antes de gravar.

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
        url = normalize_url(db_url)
        parsed = make_url(url)

        result: tuple[bool, str, int] | None = None
        if test:
            result = _run_probe(db_type, url)
            if not result[0]:
                raise ValidationError(result[1])

        with session_scope(self._session) as s:
            if s.scalar(select(Connection.id).where(Connection.name == name)) is not None:
                raise ValidationError(f"Conexão já existe: {name}")
            conn = Connection(
                id=str(uuid.uuid4()),
                name=name,
                db_type=db_type,
                db_url=url,
                host=parsed.host,
                port=parsed.port,
                database=parsed.database,
                username=parsed.username,
                is_active=True,
                last_tested=datetime.utcnow() if result else None,
                test_result=result[1] if result else None,
            )
            s.add(conn)
            s.commit()
            s.refresh(conn)
            logger.info("Conexão criada: %s (%s)", name, db_type)
            return conn

    def list(self) -> list[Connection]:
        """Lista todas as conexões (a "default" primeiro)."""
        with session_scope(self._session) as s:
            rows = list(s.scalars(select(Connection).order_by(Connection.created_at)))
            rows.sort(key=lambda c: c.id != DEFAULT_CONNECTION_ID)  # sort estável
            return rows

    def get(self, connection_id: str) -> Connection:
        """Obtém por id (ou nome). NotFoundError se não existe."""
        with session_scope(self._session) as s:
            return self._get(s, connection_id)

    def delete(self, connection_id: str) -> bool:
        """Remove a conexão e os workspaces do catálogo ligados a ela. False se não existe.

        Dados que vivem no banco remoto da conexão não são tocados.
        """
        with session_scope(self._session) as s:
            conn = s.get(Connection, connection_id)
            if conn is None:
                return False
            if conn.id == DEFAULT_CONNECTION_ID:
                raise ValidationError("A conexão default não pode ser removida")
            s.delete(conn)
            s.commit()
        db_session._connection_manager.invalidate(connection_id)
        logger.info("Conexão removida: %s", connection_id)
        return True

    def test(self, connection_id: str) -> dict[str, Any]:
        """Testa a conexão e registra last_tested/test_result. Não levanta por falha de rede."""
        with session_scope(self._session) as s:
            conn = self._get(s, connection_id)
            ok, message, latency = _run_probe(conn.db_type, conn.db_url)
            conn.last_tested = datetime.utcnow()
            conn.test_result = message
            s.commit()
            return {
                "status": "ok" if ok else "error",
                "message": message,
                "latency_ms": latency,
            }

    def update(self, connection_id: str, **fields: Any) -> Connection:
        """Atualiza name e/ou is_active. ValidationError para campos não editáveis."""
        unknown = set(fields) - set(UPDATABLE_FIELDS)
        if unknown:
            raise ValidationError(f"Campos não editáveis: {', '.join(sorted(unknown))}")
        with session_scope(self._session) as s:
            conn = self._get(s, connection_id)
            if (name := fields.get("name")) is not None:
                name = name.strip()
                if not name or len(name) > 255 or name == DEFAULT_CONNECTION_NAME:
                    raise ValidationError("name inválido ou reservado")
                conn.name = name
            if (active := fields.get("is_active")) is not None:
                if conn.id == DEFAULT_CONNECTION_ID and not active:
                    raise ValidationError("A conexão default não pode ser desativada")
                conn.is_active = bool(active)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                raise ValidationError(f"Conexão já existe: {fields.get('name')}") from None
            s.refresh(conn)
            cid = conn.id
        db_session._connection_manager.invalidate(cid)
        return conn

