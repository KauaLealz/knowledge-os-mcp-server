"""Estado só desta máquina, em JSON no home de dados (`config.KNOWLEDGE_HOME`).

- `repos.json`: repositório local -> conexão/workspace/project
  (`{repo_key: {connection_id, workspace, project, created_at, updated_at}}`).
- `usage/<connection_id>.json`: sinais de uso por item (`{item_id: {shown, opened,
  last_used_at, helped, wrong, outdated, irrelevant, verified}}`). O formato antigo
  (`{uses, last_used}`) é lido (`uses` vira `opened`) e regravado no novo na escrita seguinte.
- `searches/<connection_id>.jsonl`: uma linha `{ts, query}` por busca que voltou vazia
  (`empty_searches` agrega para o relatório).

Nada disso vai para o repositório de dados: é preferência e telemetria local. O home é lido a
cada chamada (os testes trocam `config.KNOWLEDGE_HOME`). Gravação atômica (temporário +
`os.replace`) e sob trava (thread e entre processos), para duas escritas simultâneas não
perderem uma à outra; arquivo ausente ou corrompido é lido como vazio e não é apagado — antes de
sobrescrever um arquivo corrompido, ele é guardado ao lado com o sufixo `.corrompido`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import knowledge_os.config as config
from knowledge_os.storage.access import folder_lock

logger = logging.getLogger(__name__)

_REPOS_FILE = "repos.json"
_USAGE_DIR = "usage"
_SEARCHES_DIR = "searches"
COUNTERS = ("shown", "opened", "helped", "wrong", "outdated", "irrelevant", "verified")
# Uso de verdade (abrir, ajudar) renova `last_used_at`; aparecer numa busca não.
_TOUCHES = ("opened", "helped")
_lock = threading.RLock()  # threads deste processo (UI + MCP)


@contextmanager
def _locked() -> Iterator[None]:
    """Ler-modificar-gravar sem perder escrita: trava da thread e trava entre processos
    (arquivo em `<home>/locks/`, a mesma `folder_lock` das pastas de dados)."""
    with _lock, folder_lock(Path(config.KNOWLEDGE_HOME)):
        yield


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
    with _locked():
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
    with _locked():
        data, ok = _read(path)
        if repo_key not in data:
            return False
        del data[repo_key]
        _write(path, data, was_valid=ok)
    return True


# --------------------------------------------------------------------------- uso


def _state_path(folder: str, connection_id: str, suffix: str) -> Path:
    if not connection_id or _hidden_or_nested(connection_id):
        raise ValueError(f"connection_id inválido para estado local: {connection_id!r}")
    return Path(config.KNOWLEDGE_HOME) / folder / f"{connection_id}{suffix}"


def _usage_path(connection_id: str) -> Path:
    return _state_path(_USAGE_DIR, connection_id, ".json")


def _hidden_or_nested(name: str) -> bool:
    return name.startswith(".") or "/" in name or "\\" in name


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _entry(raw: Any) -> dict[str, Any]:
    """Contadores de um item no formato novo (lê também `{uses, last_used}`)."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {name: _int(raw.get(name)) for name in COUNTERS}
    if "opened" not in raw and "uses" in raw:
        out["opened"] = _int(raw.get("uses"))
    last = raw.get("last_used_at") or raw.get("last_used")
    out["last_used_at"] = last if isinstance(last, str) and last else None
    return out


def get_usage(connection_id: str) -> dict[str, dict[str, Any]]:
    """Sinais dos itens da conexão: `{item_id: {shown, opened, last_used_at, helped, ...}}`."""
    data, _ok = _read(_usage_path(connection_id))
    return {k: _entry(v) for k, v in data.items() if isinstance(v, dict)}


def count(connection_id: str, ids: Iterable[str], field: str = "opened") -> None:
    """Soma 1 ao contador `field` de cada item (`opened`/`helped` renovam `last_used_at`).

    Best-effort: qualquer falha (inclusive `field` fora de `COUNTERS`) é logada e ignorada —
    contador nunca derruba a operação que o chamou.
    """
    try:
        if field not in COUNTERS:
            raise ValueError(f"contador desconhecido: {field!r} (válidos: {', '.join(COUNTERS)})")
        ids = list(dict.fromkeys(i for i in ids if i))
        if not ids:
            return
        path = _usage_path(connection_id)
        with _locked():
            data, ok = _read(path)
            now = _now()
            for item_id in ids:
                entry = _entry(data.get(item_id))
                entry[field] += 1
                if field in _TOUCHES:
                    entry["last_used_at"] = now
                data[item_id] = entry
            _write(path, data, was_valid=ok)
    except Exception as exc:  # noqa: BLE001 - contador nunca derruba a operação
        logger.warning("Falha ao registrar %s em %s: %s", field, connection_id, exc)


def track(connection_id: str, ids: Iterable[str], field: str = "opened") -> None:
    """Compatível com a assinatura antiga: soma `opened` (ou o `field` dado)."""
    count(connection_id, ids, field)


# --------------------------------------------------------------------------- buscas vazias


def _searches_path(connection_id: str) -> Path:
    return _state_path(_SEARCHES_DIR, connection_id, ".jsonl")


def log_empty_search(connection_id: str, query: str) -> None:
    """Registra uma busca que voltou vazia (`{ts, query}`). Best-effort, como o contador."""
    try:
        query = " ".join((query or "").split())
        if not query:
            return
        path = _searches_path(connection_id)
        line = json.dumps({"ts": _now(), "query": query}, ensure_ascii=False)
        with _locked():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao registrar busca vazia em %s: %s", connection_id, exc)


def empty_searches(connection_id: str) -> list[dict[str, Any]]:
    """Buscas vazias agregadas por consulta (sem caixa nem espaços extras):
    `[{query, count, last_at}]`, da mais repetida para a menos (empate: a mais recente)."""
    try:
        raw = _searches_path(connection_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("Não foi possível ler as buscas vazias de %s: %s", connection_id, exc)
        return []
    agg: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or not isinstance(row.get("query"), str):
            continue
        query = " ".join(row["query"].split()).casefold()
        if not query:
            continue
        entry = agg.setdefault(query, {"query": query, "count": 0, "last_at": None})
        entry["count"] += 1
        ts = row.get("ts") if isinstance(row.get("ts"), str) else None
        if ts and (entry["last_at"] is None or ts > entry["last_at"]):
            entry["last_at"] = ts
    rows = sorted(agg.values(), key=lambda e: e["last_at"] or "", reverse=True)
    rows.sort(key=lambda e: e["count"], reverse=True)
    return rows
