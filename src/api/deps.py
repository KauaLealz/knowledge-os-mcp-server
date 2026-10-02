"""Dependências FastAPI: engine, sessão e diretório de artifacts."""

from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from src.config import ARTIFACTS_DIR
from src.db.session import get_engine, get_session


def get_engine_dep() -> Engine:
    """Engine do banco default (T7 trará a seleção de connection)."""
    return get_engine()


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
