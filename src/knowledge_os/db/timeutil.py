"""Relógio do banco: datetimes naive em UTC (formato gravado desde sempre)."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Agora em UTC, sem tzinfo (substitui o `datetime.utcnow()` deprecado)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
