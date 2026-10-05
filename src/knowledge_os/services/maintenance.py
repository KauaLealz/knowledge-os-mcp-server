"""Backup e manutenção diária do banco SQLite do catálogo."""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine

from knowledge_os import config
from knowledge_os.db.timeutil import utcnow

logger = logging.getLogger(__name__)

KEEP_DAILY = 7
EPHEMERAL_GRACE_DAYS = 7
MARKER_NAME = "maintenance.last"


def _sqlite_file(engine: Engine | None) -> Path | None:
    """Arquivo do banco SQLite em uso; None para memória, SQLCipher ou outro dialect."""
    if engine is None:
        from knowledge_os.db.session import get_engine

        engine = get_engine()
    if engine.dialect.name != "sqlite" or engine.dialect.driver != "pysqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database)


def backup(reason: str, engine: Engine | None = None) -> Path | None:
    """Copia o catálogo SQLite para `<home>/backups/knowledge-<AAAAMMDD-HHMMSS>-<motivo>.db`.

    Usa a API de backup do sqlite3 (consistente com o banco em uso). No motivo "daily" mantém
    só as 7 cópias mais recentes. Devolve None, sem fazer nada, se o banco não é SQLite em
    arquivo (Postgres, MySQL, SQLCipher, memória).
    """
    src = _sqlite_file(engine)
    if src is None or not src.exists():
        logger.info("Backup automático só para SQLite em arquivo; nada feito")
        return None
    folder = config.BACKUPS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now()
    dest = folder / f"knowledge-{stamp:%Y%m%d-%H%M%S}-{reason}.db"
    while dest.exists():  # dois backups no mesmo segundo: avança o carimbo
        stamp += timedelta(seconds=1)
        dest = folder / f"knowledge-{stamp:%Y%m%d-%H%M%S}-{reason}.db"
    # Nome temporário + rename: um backup interrompido nunca ocupa o nome final (nem a rotação).
    partial = dest.with_name(dest.name + ".tmp")
    source = sqlite3.connect(src, timeout=30)
    target = sqlite3.connect(partial)
    try:
        source.backup(target)
    except BaseException:
        target.close()
        source.close()
        partial.unlink(missing_ok=True)
        raise
    target.close()
    source.close()
    partial.replace(dest)
    if reason == "daily":
        for old in sorted(folder.glob("knowledge-*-daily.db"))[:-KEEP_DAILY]:
            old.unlink(missing_ok=True)
    return dest


def _purge_expired_ephemeral(engine: Engine, now: datetime) -> int:
    from knowledge_os.db.models import Item
    from knowledge_os.db.session import get_session, run_with_retry
    from knowledge_os.services._common import purge_item_links

    cutoff = now - timedelta(days=EPHEMERAL_GRACE_DAYS)

    def work() -> int:
        s = get_session(engine)
        try:
            ids = list(s.execute(
                select(Item.id).where(
                    Item.memory_class == "ephemeral", Item.expires_at < cutoff)
            ).scalars())
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                purge_item_links(s, chunk)
                s.execute(delete(Item).where(Item.id.in_(chunk)))
            s.commit()
            return len(ids)
        finally:
            s.close()

    return run_with_retry(work)


def run_daily(now: datetime | None = None) -> dict[str, Any]:
    """Manutenção diária, no máximo uma vez por dia (marca em `<home>/maintenance.last`).

    Backup "daily", remoção dos ephemeral vencidos há mais de 7 dias e checkpoint do WAL.
    """
    from knowledge_os.db.session import get_engine

    now = now or utcnow()
    marker = config.KNOWLEDGE_HOME / MARKER_NAME
    today = now.strftime("%Y-%m-%d")
    try:
        if marker.read_text(encoding="utf-8").strip() == today:
            return {"ran": False}
    except OSError:
        pass
    engine = get_engine()
    result: dict[str, Any] = {"ran": True}
    result["backup"] = backup("daily", engine)
    result["purged"] = _purge_expired_ephemeral(engine, now)
    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    # Marca só depois de concluir: servidor morto no meio não pula a manutenção do dia.
    # Duas execuções simultâneas são inofensivas (rotação e purga são idempotentes).
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(today, encoding="utf-8")
    return result
