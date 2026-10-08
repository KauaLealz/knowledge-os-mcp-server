"""Itens do segundo cérebro como arquivos Markdown com frontmatter YAML numa pasta (a fonte de
verdade de cada conexão, um repositório git).

`FileStore` lê a pasta inteira (`**/*.md`, fora de pastas que começam com "." como `.git` e
`.secrets`) e guarda um cache por arquivo `{relpath: (mtime_ns, size, ItemRecord)}`. `refresh()`
relista a pasta e só re-parseia o que é novo ou mudou de mtime/tamanho, tirando do cache o que
sumiu — barato o bastante para ser chamado antes de cada operação. As consultas (`items`, `get`,
`by_key`...) leem o estado do último `refresh()`/`write()`/`delete()`; quem precisa ver mudanças
feitas por fora (ex.: um `git pull`) chama `refresh()` antes.

Arquivo inválido nunca derruba a leitura: vai para `errors` com o motivo. Dois arquivos com o
mesmo id: vale o de mtime mais recente e o outro também vai para `errors`.

A escrita é atômica (arquivo temporário na mesma pasta + `os.replace`) e o path segue
`item_path`; se a key, o workspace ou o project mudarem, o arquivo antigo é removido.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_file import (
    item_path,
    parse_item_file,
    safe_join,
    serialize_item,
)
from knowledge_os.storage.search import SearchIndex


@dataclass
class ItemRecord:
    """Um item como está no arquivo (campos de `parse_item_file`) + `path` relativo à raiz."""

    id: str
    key: str | None
    workspace: str | None
    project: str | None
    subject: str | None
    type: str
    title: str
    status: str
    memory_class: str
    tags: list[str]
    labels: list[str]
    scope_paths: list[str]
    confidence: Any
    importance: Any
    ttl_days: Any
    keywords: str | None
    source: str | None
    created_at: datetime
    updated_at: datetime
    relations: list[dict[str, str]]
    summary: str
    content: str
    path: str = field(default="")


_FIELDS = tuple(f for f in ItemRecord.__dataclass_fields__ if f != "path")


def _record_from_parsed(parsed: dict[str, Any], path: str) -> ItemRecord:
    return ItemRecord(**{f: parsed.get(f) for f in _FIELDS}, path=path)


def record_text(record: ItemRecord) -> tuple[str, str]:
    """(path relativo, conteúdo do arquivo) do item, como `FileStore.write` gravaria."""
    if not record.workspace or not record.project:
        raise ValidationError("Item sem workspace/project não pode ser gravado")
    rel = item_path(record.workspace, record.project, record.key, record.id)
    text = serialize_item(
        asdict(record),
        workspace_name=record.workspace,
        project_name=record.project,
        subject_name=record.subject,
        relations=list(record.relations or []),
        tags=list(record.tags or []),
        labels=list(record.labels or []),
    )
    return rel, text


def _hidden(name: str) -> bool:
    return name.startswith(".")


def _atomic_write(target: Path, text: str) -> None:
    """Grava `text` em `target` via temporário na mesma pasta + `os.replace`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class FileStore:
    """Itens de uma pasta de dados, com cache incremental e índice de busca."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.errors: dict[str, str] = {}
        self.index = SearchIndex()
        self._cache: dict[str, tuple[int, int, ItemRecord | None]] = {}
        self._parse_errors: dict[str, str] = {}
        self._by_id: dict[str, ItemRecord] = {}
        self._by_key: dict[tuple[str | None, str | None, str], ItemRecord] = {}
        self.refresh()

    # ------------------------------------------------------------------ leitura

    def _scan(self) -> dict[str, tuple[int, int]]:
        """relpath -> (mtime_ns, size) de cada `.md` fora de pastas ocultas."""
        found: dict[str, tuple[int, int]] = {}
        if not self.root.is_dir():
            return found
        # scandir em vez de walk + stat: no Windows o stat da entrada vem da própria listagem,
        # sem uma chamada extra por arquivo.
        pending: list[tuple[str, str]] = [(str(self.root), "")]
        while pending:
            folder, prefix = pending.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue  # pasta sumiu ou sem permissão: o resto da leitura segue
            for entry in entries:
                if _hidden(entry.name):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append((entry.path, f"{prefix}{entry.name}/"))
                    elif entry.name.endswith(".md") and entry.is_file():
                        st = entry.stat()
                        found[f"{prefix}{entry.name}"] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    continue  # sumiu entre a listagem e o stat
        return found

    def _load(self, rel: str, mtime_ns: int, size: int) -> None:
        try:
            raw = (self.root / rel).read_text(encoding="utf-8")
            record: ItemRecord | None = _record_from_parsed(parse_item_file(raw), rel)
            self._parse_errors.pop(rel, None)
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            record = None
            self._parse_errors[rel] = str(exc)
        self._cache[rel] = (mtime_ns, size, record)

    def refresh(self) -> None:
        """Relista a pasta; re-parseia só o que é novo ou mudou; esquece o que sumiu."""
        current = self._scan()
        for rel in [r for r in self._cache if r not in current]:
            del self._cache[rel]
            self._parse_errors.pop(rel, None)
        for rel, (mtime_ns, size) in current.items():
            cached = self._cache.get(rel)
            if cached is None or cached[0] != mtime_ns or cached[1] != size:
                self._load(rel, mtime_ns, size)
        self._rebuild()

    def _rebuild(self) -> None:
        """Recalcula o item vigente de cada id (o arquivo mais recente vence) e o índice."""
        winners: dict[str, tuple[int, str]] = {}
        duplicates: dict[str, str] = {}
        for rel, (mtime_ns, _size, record) in self._cache.items():
            if record is None:
                continue
            best = winners.get(record.id)
            if best is None or (mtime_ns, rel) > best:
                if best is not None:
                    duplicates[best[1]] = f"id duplicado {record.id!r}: vale {rel}"
                winners[record.id] = (mtime_ns, rel)
            else:
                duplicates[rel] = f"id duplicado {record.id!r}: vale {best[1]}"

        previous = self._by_id
        by_id: dict[str, ItemRecord] = {}
        for item_id, (_m, rel) in winners.items():
            record = self._cache[rel][2]
            assert record is not None
            by_id[item_id] = record
        for item_id, record in by_id.items():
            if previous.get(item_id) is not record:
                self.index.add(record)
        for item_id in previous:
            if item_id not in by_id:
                self.index.remove(item_id)

        self._by_id = by_id
        self._by_key = {
            (r.workspace, r.project, r.key): r for r in by_id.values() if r.key
        }
        self.errors = {**self._parse_errors, **duplicates}

    # ------------------------------------------------------------------ consultas

    def items(self) -> list[ItemRecord]:
        """Itens vigentes, ordenados pelo path."""
        return sorted(self._by_id.values(), key=lambda r: r.path)

    def get(self, item_id: str) -> ItemRecord | None:
        return self._by_id.get(item_id)

    def by_key(self, workspace: str, project: str, key: str) -> ItemRecord | None:
        """Item pela key dentro de workspace/project (nomes exatos, como no frontmatter)."""
        return self._by_key.get((workspace, project, key))

    def workspaces(self) -> list[str]:
        return sorted({r.workspace for r in self._by_id.values() if r.workspace})

    def projects(self, workspace: str) -> list[str]:
        return sorted(
            {r.project for r in self._by_id.values() if r.workspace == workspace and r.project}
        )

    def subjects(self, workspace: str, project: str) -> list[str]:
        return sorted(
            {
                r.subject
                for r in self._by_id.values()
                if r.workspace == workspace and r.project == project and r.subject
            }
        )

    # ------------------------------------------------------------------ escrita

    def _forget(self, rel: str) -> None:
        """Apaga o arquivo (se ainda existir) e tira do cache."""
        try:
            safe_join(self.root, rel).unlink()
        except FileNotFoundError:
            pass
        self._cache.pop(rel, None)
        self._parse_errors.pop(rel, None)

    def _paths_of(self, item_id: str) -> list[str]:
        return [
            rel for rel, (_m, _s, r) in self._cache.items() if r is not None and r.id == item_id
        ]

    def duplicates(self) -> dict[str, list[str]]:
        """id -> paths dos arquivos que perderam para o vigente (mesmo id em mais de um
        arquivo). Apagar ou regravar o item precisa levar esses junto, senão ele "volta"."""
        out: dict[str, list[str]] = {}
        for rel, (_m, _s, record) in self._cache.items():
            if record is None:
                continue
            current = self._by_id.get(record.id)
            if current is not None and current.path != rel:
                out.setdefault(record.id, []).append(rel)
        return out

    def write(self, record: ItemRecord) -> str:
        """Grava o item no seu path e devolve o path relativo.

        Qualquer outro arquivo com o mesmo id (key/workspace/project antigos, ou duplicata) é
        removido: depois da escrita sobra um arquivo só por id.
        """
        rel, text = record_text(record)
        target = safe_join(self.root, rel)
        _atomic_write(target, text)
        for old in self._paths_of(record.id):
            if old != rel:
                self._forget(old)
        st = target.stat()
        self._cache[rel] = (
            st.st_mtime_ns,
            st.st_size,
            _record_from_parsed(parse_item_file(text), rel),
        )
        self._parse_errors.pop(rel, None)
        self._rebuild()
        return rel

    def delete(self, item_id: str) -> str | None:
        """Remove o arquivo do item (e duplicatas); devolve o path vigente ou None."""
        current = self._by_id.get(item_id)
        if current is None:
            return None
        for rel in self._paths_of(item_id):
            self._forget(rel)
        self._rebuild()
        return current.path
