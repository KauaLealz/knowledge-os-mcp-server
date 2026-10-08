"""Estado só desta máquina, em JSON no home de dados (`config.KNOWLEDGE_HOME`).

- `repos.json`: repositório local -> conexão/workspace/project
  (`{repo_key: {connection_id, workspace, project, created_at, updated_at}}`).
- `usage/<connection_id>.json`: contador de uso por item (`{item_id: {uses, last_used}}`).

Nada disso vai para o repositório de dados: é preferência e telemetria local. O home é lido a
cada chamada (os testes trocam `config.KNOWLEDGE_HOME`). Gravação atômica (temporário +
`os.replace`); arquivo ausente ou corrompido é lido como vazio e não é apagado — antes de
sobrescrever um arquivo corrompido, ele é guardado ao lado com o sufixo `.corrompido`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import knowledge_os.config as config

logger = logging.getLogger(__name__)

_REPOS_FILE = "repos.json"
_USAGE_DIR = "usage"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> tuple[dict[str, Any], bool]:
    """(conteúdo, válido). Ausente conta como válido e vazio; corrompido, inválido e vazio."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, True
    except OSError as exc:
        logger.warning("Não foi possível ler %s: %s", path, exc)
        return {}, False
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Arquivo corrompido, lido como vazio: %s", path)
        return {}, False
    if not isinstance(data, dict):
        logger.warning("Arquivo com formato inesperado, lido como vazio: %s", path)
        return {}, False
    return data, True


def _write(path: Path, data: dict[str, Any], *, was_valid: bool = True) -> None:
    """Grava `data` em `path` de forma atômica, preservando antes um arquivo corrompido."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not was_valid and path.exists():
        backup = path.with_name(path.name + ".corrompido")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- repos


def _repos_path() -> Path:
    return Path(config.KNOWLEDGE_HOME) / _REPOS_FILE


def list_repos() -> dict[str, dict[str, Any]]:
    """Todas as ligações repositório -> conexão desta máquina."""
    data, _ok = _read(_repos_path())
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def get_repo(repo_key: str) -> dict[str, Any] | None:
    return list_repos().get(repo_key)


def set_repo(repo_key: str, *, connection_id: str, workspace: str, project: str) -> dict[str, Any]:
    """Cria ou atualiza a ligação do repositório (mantém `created_at` se já existia)."""
    path = _repos_path()
    data, ok = _read(path)
    now = _now()
    previous = data.get(repo_key) if isinstance(data.get(repo_key), dict) else {}
    entry = {
        "connection_id": connection_id,
        "workspace": workspace,
        "project": project,
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
    }
    data[repo_key] = entry
    _write(path, data, was_valid=ok)
    return entry


def delete_repo(repo_key: str) -> bool:
    """Remove a ligação; False se ela não existia."""
    path = _repos_path()
    data, ok = _read(path)
    if repo_key not in data:
        return False
    del data[repo_key]
    _write(path, data, was_valid=ok)
    return True


# --------------------------------------------------------------------------- uso


def _usage_path(connection_id: str) -> Path:
    if not connection_id or _hidden_or_nested(connection_id):
        raise ValueError(f"connection_id inválido para arquivo de uso: {connection_id!r}")
    return Path(config.KNOWLEDGE_HOME) / _USAGE_DIR / f"{connection_id}.json"


def _hidden_or_nested(name: str) -> bool:
    return name.startswith(".") or "/" in name or "\\" in name


def get_usage(connection_id: str) -> dict[str, dict[str, Any]]:
    """Contadores de uso dos itens da conexão (`{item_id: {uses, last_used}}`)."""
    data, _ok = _read(_usage_path(connection_id))
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def track(connection_id: str, ids: Iterable[str]) -> None:
    """Soma um uso a cada item. Best-effort: qualquer falha é logada e ignorada."""
    try:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return
        path = _usage_path(connection_id)
        data, ok = _read(path)
        now = _now()
        for item_id in ids:
            entry = data.get(item_id)
            uses = entry.get("uses", 0) if isinstance(entry, dict) else 0
            data[item_id] = {"uses": (uses if isinstance(uses, int) else 0) + 1, "last_used": now}
        _write(path, data, was_valid=ok)
    except Exception as exc:  # noqa: BLE001 - contador nunca derruba a operação
        logger.warning("Falha ao registrar uso em %s: %s", connection_id, exc)
