"""Dependências FastAPI: conexão, engine, sessão e diretório de artifacts."""

from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, Header
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from src.config import ARTIFACTS_DIR
from src.db.models import DEFAULT_CONNECTION_ID
from src.db.session import (
    check_connection,
    default_connection_id,
    get_engine,
    get_session,
)


def get_connection_id(x_connection_id: str | None = Header(default=None)) -> str:
    """Conexão dos dados: o header X-Connection-Id ou, sem ele, o default do connections.json.

    NotFoundError (404) se não existe; ValidationError (422) se está desabilitada.
    """
    cid = (x_connection_id or "").strip() or default_connection_id()
    check_connection(cid)
    return cid


def get_engine_dep(connection_id: str = Depends(get_connection_id)) -> Engine:
    """Engine da conexão do request."""
    return get_engine(connection_id)


def get_catalog_engine_dep() -> Engine:
    """Engine do catálogo: as rotas de conexões não seguem o X-Connection-Id."""
    return get_engine(DEFAULT_CONNECTION_ID)


def get_artifacts_dir() -> Path:
    """Diretório onde os arquivos de artifact são gravados."""
    return ARTIFACTS_DIR


def get_session_dep(engine: Engine = Depends(get_engine_dep)) -> Iterator[Session]:
    """Sessão por request, sempre fechada ao final."""
    session = get_session(engine)
    try:
        yield session
    finally:
        session.close()


def get_catalog_session_dep(engine: Engine = Depends(get_catalog_engine_dep)) -> Iterator[Session]:
    """Sessão do catálogo por request (rotas de conexões)."""
    session = get_session(engine)
    try:
        yield session
    finally:
        session.close()
