"""Gerenciamento de sessão SQLAlchemy."""

import os
from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, Session

from src.config import DB_PATH, DB_KEY, DB_URL
from src.db.models import Base


def init_db():
    """Inicializa banco de dados com schema."""
    engine = create_engine(
        DB_URL,
        connect_args={"check_same_thread": False, "timeout": 10},
        echo=False,
    )

    # Habilitar WAL mode para melhor concorrência
    if "sqlite" in DB_URL:
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    # Criar todas as tabelas
    Base.metadata.create_all(bind=engine)

    return engine


def get_session(engine) -> Session:
    """Retorna nova sessão SQLAlchemy."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


# Engine global
_engine = None


def get_engine():
    """Lazy-load engine."""
    global _engine
    if _engine is None:
        _engine = init_db()
    return _engine


def close_engine():
    """Fecha engine global."""
    global _engine
    if _engine:
        _engine.dispose()
        _engine = None
