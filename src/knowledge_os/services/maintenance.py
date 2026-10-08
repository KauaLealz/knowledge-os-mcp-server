"""Manutenção diária: apaga a memória temporária vencida de cada conexão e publica.

O histórico é o do git (cada remoção é um commit), então não há cópia de segurança à parte.
"""

import logging
from datetime import datetime
from typing import Any

from knowledge_os import config
from knowledge_os.services.brain import Brain, is_expired, utcnow
from knowledge_os.storage.access import load_connections

logger = logging.getLogger(__name__)

MARKER_NAME = "maintenance.last"


def purge_expired_ephemeral(brain: Brain, now: datetime) -> int:
    """Apaga os itens ephemeral vencidos (updated_at + ttl_days <= now) da conexão.

    Só eles: memória de longa duração (aprendizado, regra, decisão, procedimento) nunca expira
    sozinha — o que não serve mais sai por `deprecated`/`supersedes`, por decisão de alguém.
    """
    with brain.editing() as d:
        expired = [
            r.id for r in d.records.values()
            if r.memory_class == "ephemeral" and is_expired(r, now)
        ]
        for record_id in expired:
            d.remove(record_id)
        if expired:
            brain.commit(d, f"knowledge-os: remove {len(expired)} ephemeral vencido(s)")
    return len(expired)


def run_daily(now: datetime | None = None) -> dict[str, Any]:
    """Manutenção diária, no máximo uma vez por dia (marca em `<home>/maintenance.last`).

    Remove os ephemeral vencidos de cada conexão habilitada. Uma conexão com problema não
    impede as outras.
    """
    now = now or utcnow()
    marker = config.KNOWLEDGE_HOME / MARKER_NAME
    today = now.strftime("%Y-%m-%d")
    try:
        if marker.read_text(encoding="utf-8").strip() == today:
            return {"ran": False}
    except OSError:
        pass
    expired = 0
    for conn in load_connections().connections:
        if not conn.enabled:
            continue
        try:
            expired += purge_expired_ephemeral(Brain(conn=conn), now)
        except Exception:  # noqa: BLE001 - uma conexão fora do ar não para a manutenção
            logger.warning("Manutenção da conexão %s falhou", conn.name, exc_info=True)
    # Marca só depois de concluir: servidor morto no meio não pula a manutenção do dia.
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(today, encoding="utf-8")
    return {"ran": True, "expired": expired}
