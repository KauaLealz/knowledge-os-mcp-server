"""Helpers compartilhados pelos services."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import knowledge_os.config as config
from knowledge_os.exceptions import ValidationError
from knowledge_os.services.brain import Item, Project, Workspace

EXPORT_VERSION = "1.0"


def refuse_home_source(path: Path) -> None:
    """ValidationError se o caminho (resolvido, seguindo symlinks) está dentro do home de dados.

    Protege connections.json e o estado local de virar pasta de uma connection nova. O home é
    lido na chamada.
    """
    resolved = path.resolve()
    if resolved.is_relative_to(config.KNOWLEDGE_HOME.resolve()):
        raise ValidationError("Caminho dentro do home de dados não é permitido")


def utc_now_iso() -> str:
    """Timestamp UTC em ISO 8601."""
    return datetime.now(UTC).isoformat()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def workspace_to_dict(ws: Workspace) -> dict[str, Any]:
    """Serializa um Workspace."""
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "created_at": _iso(ws.created_at),
        "updated_at": _iso(ws.updated_at),
    }


def project_to_dict(dm: Project) -> dict[str, Any]:
    """Serializa um Project."""
    return {
        "id": dm.id,
        "workspace_id": dm.workspace_id,
        "name": dm.name,
        "description": dm.description,
        "created_at": _iso(dm.created_at),
        "updated_at": _iso(dm.updated_at),
    }


def item_to_dict(item: Item) -> dict[str, Any]:
    """Serializa um Item (com nomes de tags e labels)."""
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "project_id": item.project_id,
        "type": item.type,
        "memory_class": item.memory_class,
        "title": item.title,
        "summary": item.summary,
        "content": item.content,
        "confidence": item.confidence,
        "importance": item.importance,
        "ttl_days": item.ttl_days,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
        "tags": sorted(item.tags),
        "labels": sorted(item.labels),
    }
