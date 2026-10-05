"""Database migrations: bootstrap e schema management."""

import logging
import uuid

from sqlalchemy.orm import Session

from knowledge_os.db.models import DEFAULT_CONNECTION_ID, Label
from knowledge_os.db.session import get_engine, init_db

logger = logging.getLogger(__name__)

# Labels padrão controladas
DEFAULT_LABELS = [
    "official",
    "critical",
    "experimental",
    "deprecated",
    "reference",
]


def bootstrap_labels(session: Session) -> None:
    """Insere labels padrão no banco (idempotente)."""
    for label_name in DEFAULT_LABELS:
        existing = session.query(Label).filter_by(name=label_name).first()
        if not existing:
            label = Label(id=str(uuid.uuid4()), name=label_name)
            session.add(label)
            logger.debug(f"Inserindo label: {label_name}")
    session.commit()


def bootstrap() -> None:
    """
    Executa bootstrap completo:
    1. Inicializa o banco catálogo (schema); o default do connections.json só abre no uso
    2. Insere labels padrão

    Idempotente: seguro rodar múltiplas vezes.
    """
    try:
        # Inicializa banco (cria tabelas, FTS5, triggers)
        engine = init_db(get_engine(DEFAULT_CONNECTION_ID))

        # Insere labels padrão
        session = Session(bind=engine)
        try:
            bootstrap_labels(session)
            logger.info("Bootstrap concluído com sucesso")
        finally:
            session.close()

    except Exception as exc:
        logger.error(f"Erro durante bootstrap: {exc}")
        raise
