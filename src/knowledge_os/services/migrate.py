"""Migração única dos dados antigos (v2) para o formato v6, na pasta de uma conexão.

O parser do v6 (`item_file.parse_item_file`) recusa o formato antigo de propósito — a
compatibilidade em runtime (`translate_legacy`) saiu. Este módulo lê o frontmatter antigo
direto do YAML e reescreve cada `.md` e cada `.knowledge.yaml` no formato v6, uma vez. É
idempotente: um arquivo já em v6 passa intacto.

Conversões (frontmatter de item):
- `type: spec` → `work`.
- `subtype` → vira uma tag (o próprio valor).
- `status` → o que não é `active` vira tag: `draft`/`done` (de `work`) como tag de ciclo; o
  resto (`review`, `archived`, `superseded`, `deprecated`) vira `archived`.
- `scope`, `origin`, `ttl_days`, `keywords`, `source` → removidos.
- `links: [{title, url}]` → `[{url[, title]}]`; `scope_paths: [...]` → `[{path}, ...]`;
  `relations: [{type, target}]` → `[{item: target, rel}]` (só `depends_on` mantém; o resto
  vira `relates_to`) — tudo somado em `links`.

`.knowledge.yaml`: tira `scope` da raiz e de cada `subjects[]`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from knowledge_os.services.item_file import (
    _FRONTMATTER_RE,
    _parse_dt,
    load_yaml_text,
    serialize_item,
)
from knowledge_os.storage.access import resolve_connection

_V2_MARKERS = ("subtype", "scope", "origin", "ttl_days", "keywords", "source", "status",
               "relations", "scope_paths", "verified_at", "verified_commit")
_STATUS_ARCHIVED = ("review", "archived", "superseded", "deprecated")


def _needs_item_migration(data: dict[str, Any]) -> bool:
    # `status` é campo obrigatório no v2 e não existe no v6: o marcador mais confiável. Os
    # demais campos v2 e `type: spec` cobrem o resto. (Um link {url, title} tem a mesma forma
    # no v2 e no v6, então não serve de marcador.)
    return data.get("type") == "spec" or any(m in data for m in _V2_MARKERS)


def _to_v6_links(data: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for lk in data.get("links") or []:
        if not isinstance(lk, dict):
            continue
        if lk.get("url"):
            out.append({"url": lk["url"], **({"title": lk["title"]} if lk.get("title") else {})})
        elif lk.get("item") and lk.get("rel"):  # já v6
            out.append({"item": lk["item"], "rel": lk["rel"]})
        elif lk.get("path"):
            out.append({"path": lk["path"]})
    for p in data.get("scope_paths") or []:
        if isinstance(p, str):
            out.append({"path": p})
    for r in data.get("relations") or []:
        if isinstance(r, dict) and r.get("target"):
            rel = "depends_on" if r.get("type") == "depends_on" else "relates_to"
            out.append({"item": r["target"], "rel": rel})
    return out


def _to_v6_tags(data: dict[str, Any], item_type: str) -> list[str]:
    tags = [t for t in (data.get("tags") or []) if isinstance(t, str)]
    if data.get("subtype"):
        tags.append(str(data["subtype"]))
    status = data.get("status")
    if item_type == "work" and status in ("draft", "done"):
        tags.append(status)
    elif status in _STATUS_ARCHIVED:
        tags.append("archived")
    return list(dict.fromkeys(tags))  # sem duplicatas, na ordem


def migrate_item_text(raw: str) -> str | None:
    """Reescreve o conteúdo de um `.md` antigo no formato v6, ou None se já é v6."""
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        return None
    data = load_yaml_text(match.group(1), "Frontmatter")
    if not isinstance(data, dict) or not _needs_item_migration(data):
        return None
    content = match.group(2)
    item_type = "work" if data.get("type") == "spec" else data.get("type")
    item = {
        "id": data.get("id"), "key": data.get("key"), "type": item_type,
        "title": data.get("title"), "summary": data.get("summary"), "content": content,
        "created_at": _parse_dt(data["created_at"], "created_at"),
        "updated_at": _parse_dt(data["updated_at"], "updated_at"),
    }
    return serialize_item(
        item, workspace_name=data.get("workspace"), project_name=data.get("project"),
        subject_name=data.get("subject"), links=_to_v6_links(data),
        tags=_to_v6_tags(data, item_type),
    )


def migrate_meta_text(raw: str) -> str | None:
    """Reescreve um `.knowledge.yaml` sem `scope` (raiz e subjects), ou None se já não tem."""
    data = load_yaml_text(raw, ".knowledge.yaml")
    if not isinstance(data, dict):
        return None
    changed = data.pop("scope", None) is not None
    subjects = data.get("subjects")
    if isinstance(subjects, list):
        for s in subjects:
            if isinstance(s, dict) and s.pop("scope", None) is not None:
                changed = True
    if not changed:
        return None
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _iter_files(root: Path):
    for path in root.rglob("*"):
        # Pula o que está dentro de pasta oculta (.git, .secrets); o `.knowledge.yaml` não é
        # oculto por ser um arquivo (só o nome começa com ".").
        if any(part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        if path.is_file() and (path.suffix == ".md" or path.name == ".knowledge.yaml"):
            yield path


def migrate_connection(connection_id: str | None = None, *, dry_run: bool = False
                       ) -> dict[str, Any]:
    """Migra a pasta de uma conexão para o v6. Devolve o resumo com os caminhos tocados."""
    conn = resolve_connection(connection_id)
    root = conn.clone_path()
    changed: list[str] = []
    for path in _iter_files(root):
        raw = path.read_text(encoding="utf-8")
        new = migrate_meta_text(raw) if path.name == ".knowledge.yaml" else migrate_item_text(raw)
        if new is None or new == raw:
            continue
        rel = path.relative_to(root).as_posix()
        changed.append(rel)
        if not dry_run:
            path.write_text(new, encoding="utf-8", newline="\n")
    return {"connection": conn.id, "dry_run": dry_run, "migrated": len(changed),
            "changed": changed}
