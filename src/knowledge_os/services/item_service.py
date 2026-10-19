"""Itens do segundo cérebro (v6): salvar em lote, ler, buscar e apagar.

Toda escrita monta um rascunho (`brain.Draft`) e publica de uma vez pelo repositório git da
conexão: em `review_mode="direct"` grava e comita; em `review_mode="pr"` abre PR/Issue.

Alcance (v6): não há `scope`. Um item vale onde mora na hierarquia (workspace → project →
subject) e abaixo. Quem olha de um repositório ligado passa `viewpoint = (ws_id, pj_id)`
(slugs) e enxerga o que mora nesse project ou no workspace dele; pasta não ligada (`None`) não
enxerga nada e recebe `suggestion`. O cérebro resolve a distância (`Snapshot.reaches`,
`Snapshot.reach_distance`).

Nuance e ciclo vivem em TAGS (não há status/subtype/origin/ttl/keywords/source), e `links` é
unificado ({item, rel} | {url[, title]} | {path}).
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import (
    TYPES,
    key_problem,
    key_warnings,
    validate_entry,
)
from knowledge_os.services.brain import (
    Brain,
    Draft,
    Item,
    Snapshot,
    check_name,
    meta_location,
    utcnow,
)
from knowledge_os.services.item_file import slugify
from knowledge_os.services.relation_service import review_fields
from knowledge_os.services.secret_guard import ensure_no_secrets, find_secret
from knowledge_os.services.secret_service import item_url
from knowledge_os.services.tag_service import TagService
from knowledge_os.storage import local_state
from knowledge_os.storage.files import ItemRecord
from knowledge_os.storage.search import Candidate, Hit, paths_match
from knowledge_os.storage.search import search as rank

logger = logging.getLogger(__name__)

MAX_BATCH = 20
MAX_QUERIES = 5
MAX_LIMIT = 100
SIMILAR_LIMIT = 3
# Limpeza (candidatos do `delete` sem keys/ids).
ARCHIVED_DAYS = 90
UNUSED_DAYS = 90
REASONS = ("archived", "unused")
ARCHIVED_TAG = "archived"

Viewpoint = tuple[str, str] | None

SUGGESTION = (
    "Pasta não ligada a um project: ligue com "
    'repo(action="link", repo=".", workspace="<workspace>", project="<project>").'
)

# Campos que trariam o valor de um segredo pelo agente: recusados no item_save.
VALUE_FIELDS = frozenset({"value", "valor", "secret_value", "secret", "token", "password",
                          "senha", "api_key", "apikey"})
# Palavra com cara de credencial aleatória (16+ caracteres, maiúscula, minúscula e dígito).
_RANDOM_WORD = re.compile(r"\S{16,}")
_TEXT_FIELDS = ("title", "summary", "content")
# Campos da entrada que viram campo do arquivo (o resto é local ou identidade).
_RECORD_FIELDS = ("key", "type", "title", "summary", "content", "tags", "links")

# Grupos do "essencial" (busca sem consulta, de um repositório ligado), nesta ordem.
GROUPS: tuple[tuple[str, Callable[[ItemRecord], bool]], ...] = (
    ("seguranca", lambda r: "security" in (r.tags or [])),
    ("regras", lambda r: r.type == "rule" and "security" not in (r.tags or [])),
    ("contexto", lambda r: r.type == "context"),
    ("specs", lambda r: r.type == "work"),
)


def _looks_random(text: str | None) -> bool:
    for word in _RANDOM_WORD.findall(text or ""):
        if (any(c.islower() for c in word) and any(c.isupper() for c in word)
                and any(c.isdigit() for c in word)):
            return True
    return False


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value else None


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None


def _where(record: ItemRecord) -> str:
    """Local do item: workspace/project[/subject]."""
    parts = [record.workspace or "", record.project or ""]
    if record.subject:
        parts.append(record.subject)
    return "/".join(p for p in parts if p)


def _path_links(record: ItemRecord) -> bool:
    return any("path" in lk for lk in record.links or [])


def _reach(snap: Snapshot, viewpoint: Viewpoint) -> list[tuple[ItemRecord, float]]:
    """(item, distância) de tudo que alcança o `viewpoint` (ws_id, pj_id). Sem viewpoint, nada
    (v6 não tem alcance global). Distância menor = mais perto (subject 0, project 1, ws 2)."""
    if viewpoint is None:
        return []
    ws_id, pj_id = viewpoint
    return [(r, snap.reach_distance(r, ws_id, pj_id)) for r in snap.records.values()
            if snap.reaches(r, ws_id, pj_id)]


def resolve_key(snap: Snapshot, ref: str, viewpoint: Viewpoint) -> ItemRecord | None:
    """Item pela key, o mais próximo que alcança o `viewpoint` (None se nenhum)."""
    cands = sorted(((r, dist) for r, dist in _reach(snap, viewpoint) if r.key == ref),
                   key=lambda rc: rc[1])
    return cands[0][0] if cands else None


def signal_boost(record: ItemRecord, use: dict[str, Any] | None) -> float:
    """Peso dos sinais de uso no ranking: `1 + 0.1·ln(1 + opened)` (quanto mais aberto, mais
    perto do topo). v6 não tem feedback, então só a abertura conta."""
    opened = int((use or {}).get("opened") or 0)
    return 1 + 0.1 * math.log(1 + opened)


def _batch(items: Any, what: str, limit: int = MAX_BATCH) -> list[Any]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValidationError(f"{what} deve ser uma lista (até {limit})")
    if len(items) > limit:
        raise ValidationError(f"no máximo {limit} {what} por chamada (recebi {len(items)})")
    return items


def _choices(name: str, value: Any, valid: tuple[str, ...]) -> set[str] | None:
    """Filtro de busca: texto ou lista de textos, todos em `valid` (senão erro com a lista)."""
    if value is None or value == [] or value == "":
        return None
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValidationError(f"{name} deve ser texto ou lista de textos: {value!r}")
    bad = [v for v in values if v not in valid]
    if bad:
        raise ValidationError(f"{name} inválido: {', '.join(bad)}. Válidos: {', '.join(valid)}")
    return set(values)


def _texts(name: str, value: Any) -> list[str] | None:
    if value is None or value == []:
        return None
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValidationError(f"{name} deve ser lista de textos: {value!r}")
    return [v for v in values if v.strip()] or None


class ItemService:
    """Itens da conexão (a informada ou a padrão). Ver a docstring do módulo."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def brain(self) -> Brain:
        return Brain(self._connection_id)

    # ------------------------------------------------------------------ resolução

    def resolve_workspace_id(self, ref: str) -> str:
        return self.brain().snapshot.workspace(ref).id

    def resolve_project_id(self, workspace_id: str, ref: str) -> str:
        return self.brain().snapshot.project(workspace_id, ref).id

    def resolve_subject_id(self, workspace_id: str, project_id: str, ref: str) -> str:
        return self.brain().snapshot.subject(workspace_id, project_id, ref).id

    def ensure_location(self, workspace: str, project: str) -> tuple[str, str]:
        """Workspace e project por nome ou id; os que faltam são criados (`.knowledge.yaml`)."""
        brain = self.brain()
        with brain.editing() as d:
            ws_name, pj_name = location_names(d, workspace, project)
            ws_id, pj_id = slugify(ws_name), slugify(pj_name)
            if d.find_workspace(ws_id) is None:
                d.set_meta(meta_location(ws_id), {"name": ws_name})
            if d.find_project(ws_id, pj_id) is None:
                d.set_meta(meta_location(ws_id, pj_id), {"name": pj_name})
            brain.commit(d, f"knowledge-os: cria {ws_name}/{pj_name}")
        return ws_id, pj_id

    # ------------------------------------------------------------------ save

    def save(
        self, items: list[dict[str, Any]], default_location: tuple[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Grava até 20 itens numa publicação só; cada entrada escolhe o modo pelo que traz
        (`key` = upsert no project; `id` = atualiza/move; nenhum = cria). Valida por
        `model.validate_entry`. A key de um item existente não muda. Segredo: item `secret` com
        key e sem corpo. Qualquer erro desfaz o lote e aponta a entrada."""
        entries = _batch(items, "itens")
        if not entries:
            return []
        for i, raw in enumerate(entries):
            if not isinstance(raw, dict):
                raise ValidationError(f"Entrada {i}: cada item deve ser um objeto")
            if VALUE_FIELDS & {str(k).lower() for k in raw}:
                raise ValidationError(
                    f"Entrada {i}: o valor de um segredo não passa pelo agente. Grave o item "
                    "(type secret) sem valor e passe ao usuário o fill_url da resposta."
                )
        brain = self.brain()
        rows: list[dict[str, Any]] = []
        with brain.editing() as d:
            for i, raw in enumerate(entries):
                label = raw.get("key") or raw.get("id") or raw.get("title") or "?"
                try:
                    row = self._save_one(brain, d, raw, default_location)
                except (ValidationError, NotFoundError) as exc:
                    raise ValidationError(f"Entrada {i} ({label}): {exc}") from exc
                rows.append({"index": i, **row})
            publish = brain.commit(d, f"knowledge-os: salva {len(entries)} item(ns)")
        if publish is not None and publish.status != "published":
            return [{"index": r["index"], "id": r["id"], "key": r["key"],
                     **review_fields(publish)} for r in rows]
        for row in rows:
            record = brain.snapshot.get(row["id"])
            if record is not None:
                row["url"] = record_url(brain, record)
                if record.type == "secret":
                    row["has_value"] = brain.view(record).has_value
                    row["fill_url"] = row["url"]
        return rows

    def _save_one(self, brain: Brain, d: Draft, raw: dict[str, Any],
                  default_location: tuple[str, str] | None) -> dict[str, Any]:
        item_id, key = raw.get("id"), raw.get("key")
        ws_ref, pj_ref = raw.get("workspace"), raw.get("project")
        if pj_ref and not ws_ref:
            raise ValidationError("informe o workspace do project (ou nenhum dos dois, para usar "
                                  "o project ligado ao repo)")
        existing: ItemRecord | None = None
        names: tuple[str, str] | None = None
        if item_id is not None:
            if not isinstance(item_id, str) or not item_id.strip():
                raise ValidationError("id deve ser o id (texto) de um item existente")
            existing = d.get(item_id)
            if existing is None:
                raise NotFoundError(f"Item não encontrado: id {item_id}. Confira o id "
                                    "(item_search) ou use a key")
            if ws_ref:
                names = location_names(d, ws_ref, pj_ref)
        else:
            if ws_ref:
                names = location_names(d, ws_ref, pj_ref)
            elif default_location:
                names = location_names(d, *default_location)
            else:
                raise ValidationError("informe workspace e project (ou repo, para usar o "
                                      "project ligado)")
            if key is not None:
                problem = key_problem(key)
                if problem:
                    raise ValidationError(problem)
                existing = d.by_key(slugify(names[0]), slugify(names[1] or ""), key)
                if existing is None:
                    _refuse_case_clash(d, names, key, None)

        probe = dict(raw)
        if existing is not None and "type" not in probe:
            probe["type"] = existing.type
        clean, _ = validate_entry(probe)
        if existing is not None and "type" not in raw:
            clean.pop("type", None)
        ensure_no_secrets(**{f: clean.get(f) for f in _TEXT_FIELDS if f in clean})
        _refuse_credentials(clean)

        similar: list[dict[str, Any]] = []
        if existing is None:
            assert names is not None
            record = self._create(brain, d, clean, names, raw.get("subject"))
            action = "created"
            if record.key is None:
                similar = similar_in(d, slugify(names[0]), record.title, exclude=record.id)
        else:
            record, action = self._update(brain, d, existing, clean,
                                          names if item_id is not None else None,
                                          "subject" in raw, raw.get("subject"))
        warnings: list[str] = []
        if action == "created":
            warnings += key_warnings(record.key, record.type)
        if clean.get("tags"):
            warnings += TagService.ensure_in_draft(d, clean["tags"])
        row: dict[str, Any] = {"id": record.id, "key": record.key, "action": action,
                               "warnings": warnings}
        if similar:
            row["similar"] = similar
        return row

    @staticmethod
    def _create(brain: Brain, d: Draft, clean: dict[str, Any], names: tuple[str, str],
                subject_ref: str | None) -> ItemRecord:
        missing = [f for f in ("type", "title", "summary") if not clean.get(f)]
        if missing:
            raise ValidationError(
                f"para criar um item informe {', '.join(missing)} (ex.: {{\"key\": "
                "\"rule/money\", \"type\": \"rule\", \"title\": \"...\", \"summary\": \"...\"})"
            )
        ws_name, pj_name = names
        now = utcnow()
        record = ItemRecord(
            id=str(uuid.uuid4()), key=clean.get("key"), workspace=ws_name, project=pj_name,
            subject=subject_name(d, ws_name, pj_name, subject_ref) if subject_ref else None,
            type=clean["type"], title=clean["title"], tags=sorted(clean.get("tags") or []),
            links=list(clean.get("links") or []), created_at=now, updated_at=now,
            summary=clean["summary"], content=clean.get("content") or "",
        )
        record = _checked(brain, record, None, clean)
        return d.put(record)

    @staticmethod
    def _update(brain: Brain, d: Draft, existing: ItemRecord, clean: dict[str, Any],
                move_to: tuple[str, str] | None, subject_given: bool,
                subject_ref: str | None) -> tuple[ItemRecord, str]:
        if clean.get("key") and existing.key and clean["key"] != existing.key:
            raise ValidationError(
                f"a key de um item existente não muda (atual: {existing.key!r}). Para outro "
                "nome, crie um item novo e ligue com links (rel depends_on/relates_to)"
            )
        changes: dict[str, Any] = {}
        for name in _RECORD_FIELDS:
            if name not in clean:
                continue
            value = clean[name]
            if name == "key" and value is None:
                continue
            if name == "tags":
                value = sorted(value)
            elif name == "content":
                value = value or ""
            if getattr(existing, name) != value:
                changes[name] = value
        if move_to is not None:
            ws_name, pj_name = move_to
            subject = subject_name(d, ws_name, pj_name, subject_ref) if subject_ref else None
            place = {"workspace": ws_name, "project": pj_name, "subject": subject}
        elif subject_given:
            subject = (subject_name(d, existing.workspace or "", existing.project or "",
                                    subject_ref) if subject_ref else None)
            place = {"subject": subject}
        else:
            place = {}
        place = {k: v for k, v in place.items() if getattr(existing, k) != v}
        if not changes and not place:
            return existing, "unchanged"
        record = _checked(brain, dataclasses.replace(existing, **changes, **place), existing,
                          clean)
        if record.key and ("workspace" in place or "project" in place):
            clash = d.by_key(slugify(record.workspace or ""), slugify(record.project or ""),
                             record.key or "")
            if clash is not None and clash.id != record.id:
                raise ValidationError(f"já existe item com key {record.key!r} no project de "
                                      "destino")
            _refuse_case_clash(d, (record.workspace or "", record.project or ""), record.key,
                               record.id)
        return d.put(dataclasses.replace(record, updated_at=utcnow())), "updated"

    # ------------------------------------------------------------------ leitura

    def get(self, item_id: str) -> Item:
        brain = self.brain()
        return brain.view(brain.snapshot.require(item_id))

    def get_by_key(self, workspace_id: str, project_id: str, key: str) -> Item:
        brain = self.brain()
        record = brain.snapshot.by_key(workspace_id, project_id, key)
        if record is None:
            raise NotFoundError(f"Item não encontrado: key {key!r}")
        return brain.view(record)

    def get_many(self, keys: list[str] | None = None, ids: list[str] | None = None,
                 viewpoint: Viewpoint = None, workspace: str | None = None,
                 project: str | None = None) -> list[dict[str, Any]]:
        """Até 20 itens completos, na ordem pedida (keys, depois ids); soma `opened`."""
        keys, ids = _texts("keys", keys) or [], _texts("ids", ids) or []
        if not keys and not ids:
            raise ValidationError('informe keys ou ids (ex.: item_get(keys=["rule/money"]))')
        if len(keys) + len(ids) > MAX_BATCH:
            raise ValidationError(f"no máximo {MAX_BATCH} itens por chamada "
                                  f"(recebi {len(keys) + len(ids)})")
        if bool(workspace) != bool(project):
            raise ValidationError("informe workspace e project juntos")
        brain = self.brain()
        snap = brain.snapshot
        place: tuple[str, str] | None = None
        if workspace:
            ws = snap.find_workspace(workspace)
            pj = snap.find_project(ws.id, project) if ws else None
            place = (ws.id, pj.id) if ws and pj else ("", "")
        rows: list[dict[str, Any]] = []
        opened: list[str] = []
        now = utcnow()
        for kind, ref in [("key", k) for k in keys] + [("id", i) for i in ids]:
            if kind == "id":
                record = snap.get(ref)
            elif place is not None:
                record = snap.by_key(place[0], place[1], ref)
            else:
                record = resolve_key(snap, ref, viewpoint)
            if record is None:
                rows.append({kind: ref, "missing": True})
                continue
            rows.append(full_dict(brain, record, now))
            opened.append(record.id)
        brain.count(opened, "opened")
        return rows

    # ------------------------------------------------------------------ busca

    def search(
        self,
        query: str = "",
        queries: list[str] | None = None,
        viewpoint: Viewpoint = None,
        workspace: str | None = None,
        everywhere: bool = False,
        paths: list[str] | None = None,
        types: list[str] | str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        content_head: int | None = None,
    ) -> dict[str, Any]:
        """Busca explicada pela hierarquia; nunca devolve o `content` inteiro.

        Pool: `everywhere=True` → tudo; `workspace=` → o workspace inteiro; senão o que alcança
        `viewpoint`. Esconde itens com a tag `archived` (passe `tags=["archived"]` para vê-los).
        `paths` sobe quem casa um link de caminho (com `excerpt`) e, sem consulta, tira quem tem
        link de caminho de outro lugar. Com `queries` (até 5): `{groups: [{query, results}]}`.
        Sem consulta, de um repositório ligado e sem filtros: o essencial em
        `{groups: [{group, results}]}`. Pasta não ligada leva `suggestion`.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise ValidationError(f"limit deve ser inteiro de 1 a {MAX_LIMIT}: {limit!r}")
        if queries is not None:
            queries = _batch(queries, "consultas", MAX_QUERIES)
            if not queries or not all(isinstance(q, str) and q.strip() for q in queries):
                raise ValidationError("queries deve ser uma lista de 1 a 5 consultas não vazias")
        query = (query or "").strip()
        paths = _texts("paths", paths)
        type_set = _choices("types", types, tuple(TYPES))
        tag_list = _texts("tags", tags)
        show_archived = bool(tag_list and ARCHIVED_TAG in tag_list)

        brain = self.brain()
        snap = brain.snapshot

        browsing = not query.strip() and not queries

        def wanted(r: ItemRecord) -> bool:
            tags_set = set(r.tags or [])
            if not show_archived and ARCHIVED_TAG in tags_set:
                return False
            if type_set and r.type not in type_set:
                return False
            if tag_list and not set(tag_list) <= tags_set:
                return False
            return not (browsing and paths and _path_links(r) and not paths_match(r, paths))

        usage = brain.usage()
        cands = [Candidate(r, dist, signal_boost(r, usage.get(r.id)))
                 for r, dist in self._pool(snap, viewpoint, workspace, everywhere) if wanted(r)]
        shown: list[str] = []

        def run(text: str, pool: list[Candidate]) -> list[dict[str, Any]]:
            hits = rank(pool, text, limit, index=brain.store.index, paths=paths)
            if text and not hits:
                local_state.log_empty_search(brain.cid, text)
            shown.extend(h.record.id for h in hits)
            return [result_dict(brain, h, paths, content_head) for h in hits]

        filtered = any(v is not None for v in (paths, type_set, tag_list))
        out: dict[str, Any]
        if queries is not None:
            out = {"groups": [{"query": q, "results": run(q.strip(), cands)} for q in queries]}
        elif (not query and viewpoint is not None and not workspace and not everywhere
              and not filtered):
            out = {"groups": [{"group": name, "results": run("", [c for c in cands
                                                                  if pick(c.record)])}
                              for name, pick in GROUPS]}
        else:
            out = {"results": run(query, cands)}
        if viewpoint is None and not workspace and not everywhere:
            out["suggestion"] = SUGGESTION
        brain.count(shown, "shown")
        return out

    @staticmethod
    def _pool(snap: Snapshot, viewpoint: Viewpoint, workspace: str | None,
              everywhere: bool) -> list[tuple[ItemRecord, float]]:
        if everywhere:
            return [(r, 0.0) for r in snap.records.values()]
        if workspace:
            ws = snap.find_workspace(workspace)
            if ws is None:
                known = ", ".join(w.name for w in snap.workspaces()) or "(nenhum)"
                raise NotFoundError(f"Workspace não encontrado: {workspace}. Existentes: {known}")
            return [(r, 0.0) for r in snap.records.values()
                    if slugify(r.workspace or "") == ws.id]
        return _reach(snap, viewpoint)

    def similar(self, workspace_id: str, title: str, limit: int = SIMILAR_LIMIT,
                ) -> list[dict[str, Any]]:
        return similar_in(self.brain().snapshot, workspace_id, title, limit)

    def track_use(self, ids: list[str]) -> None:
        if ids:
            self.brain().count(ids, "opened")

    # ------------------------------------------------------------------ delete

    def delete(self, keys: list[str] | None = None, ids: list[str] | None = None,
               viewpoint: Viewpoint = None, confirm: bool = False) -> dict[str, Any]:
        """Sem `keys`/`ids`: `{candidates: [{key, id, reason}]}` (reason ∈ `archived`, `unused`).
        Com `keys`/`ids` e sem `confirm`: `{status: "preview", items, missing?}`. `confirm=True`:
        apaga (e o valor de um segredo), num commit."""
        keys, ids = _texts("keys", keys) or [], _texts("ids", ids) or []
        brain = self.brain()
        if not keys and not ids:
            return {"candidates": self._candidates(brain, viewpoint)}
        if len(keys) + len(ids) > MAX_BATCH:
            raise ValidationError(f"no máximo {MAX_BATCH} itens por chamada "
                                  f"(recebi {len(keys) + len(ids)})")
        with brain.editing() as d:
            found: dict[str, ItemRecord] = {}
            missing: list[str] = []
            for kind, ref in [("key", k) for k in keys] + [("id", i) for i in ids]:
                record = (d.get(ref) if kind == "id" else resolve_key(d, ref, viewpoint))
                if record is None:
                    missing.append(ref)
                else:
                    found.setdefault(record.id, record)
            extra = {"missing": missing} if missing else {}
            if not confirm:
                incoming: dict[str, int] = {}
                for rel in d.relations():
                    incoming[rel.target_item_id] = incoming.get(rel.target_item_id, 0) + 1
                items = [{"id": r.id, "key": r.key, "type": r.type, "title": r.title,
                          "where": _where(r), "relations_in": incoming.get(r.id, 0)}
                         for r in found.values()]
                return {"status": "preview", "items": items, **extra}
            for record_id in found:
                d.remove(record_id)
            publish = brain.commit(d, f"knowledge-os: remove {len(found)} item(ns)")
        gone = list(found)
        if publish is not None and publish.status != "published":
            return {"ids": gone, **review_fields(publish), **extra}
        for record_id in gone:
            brain.secret_path(record_id).unlink(missing_ok=True)
        logger.info("Itens removidos: %s", gone)
        return {"status": "deleted", "ids": gone, **extra}

    def remove(self, item_id: str) -> bool:
        result = self.delete(ids=[item_id], confirm=True)
        if result.get("missing"):
            raise NotFoundError(f"Item não encontrado: {item_id}")
        return result.get("status") == "deleted"

    @staticmethod
    def _candidates(brain: Brain, viewpoint: Viewpoint) -> list[dict[str, Any]]:
        snap = brain.snapshot
        now = utcnow()
        usage = brain.usage()
        records = ([r for r, _ in _reach(snap, viewpoint)] if viewpoint is not None
                   else list(snap.records.values()))
        out = []
        for record in records:
            reason = cleanup_reason(record, usage.get(record.id), now)
            if reason:
                out.append({"key": record.key, "id": record.id, "reason": reason})
        out.sort(key=lambda c: (REASONS.index(c["reason"]), c["key"] or "", c["id"]))
        return out

    # ------------------------------------------------------------------ finos (API, hook)

    def create(self, workspace_id: str, project_id: str, subject_id: str | None = None,
               **fields: Any) -> Item:
        """Cria um item (campos de `model.ITEM_FIELDS`) e devolve o `brain.Item`."""
        if "id" in fields:
            raise ValidationError("para criar um item não envie id (ele é gerado); para editar "
                                  "um existente use update (PUT /api/items/{id})")
        entry = {**fields, "workspace": workspace_id, "project": project_id}
        entry.pop("subject", None)
        if subject_id:
            entry["subject"] = subject_id
        return self._saved(self.save([entry])[0])

    def update(self, item_id: str, **fields: Any) -> Item:
        """Atualiza só os campos informados (tags substituem as atuais)."""
        return self._saved(self.save([{**fields, "id": item_id}])[0])

    def _saved(self, row: dict[str, Any]) -> Item:
        if "action" not in row:  # modo PR: só existe depois do merge
            raise ValidationError(f"Mudança aguardando revisão: {row.get('pr_url') or row}")
        return self.get(row["id"])


# --------------------------------------------------------------------------- helpers


def _refuse_case_clash(snap: Snapshot, names: tuple[str, str | None], key: str,
                       exclude: str | None) -> None:
    clash = snap.key_clash(slugify(names[0]), slugify(names[1] or ""), key, exclude)
    if clash is not None:
        onde = f"no project {names[1]}" if names[1] else "no workspace"
        raise ValidationError(f"já existe `{clash.key}` (a caixa não diferencia) {onde}: use "
                              "essa key para atualizar o item, ou outro nome")


_CREDENTIAL_HINT = (
    "tire a credencial do valor (numa URL, deixe só o endereço: sem usuário:senha nem token "
    "na query); para guardar o segredo, grave um item type secret (key secret/<nome>) sem "
    "valor e passe ao usuário o fill_url da resposta."
)


def _refuse_credentials(clean: dict[str, Any]) -> None:
    """Os links (url, título e path) também passam pelo detector de segredo: uma URL com
    `usuário:senha@` ou `?api_key=...` vazaria para todo agente que lê o item."""
    fields: list[tuple[str, str | None]] = []
    for i, link in enumerate(clean.get("links") or []):
        fields += [(f"links[{i}].url", link.get("url")), (f"links[{i}].title", link.get("title")),
                   (f"links[{i}].path", link.get("path"))]
    for name, value in fields:
        kind = find_secret(value)
        if kind:
            raise ValidationError(f"'{name}' parece conter um segredo ({kind}): {_CREDENTIAL_HINT}")


def _checked(brain: Brain, record: ItemRecord, old: ItemRecord | None,
             clean: dict[str, Any]) -> ItemRecord:
    """Regras do item já mesclado (v6: só as de secret; nuance/ciclo é tag, não campo)."""
    if old is not None and old.type == "secret" and record.type != "secret" and (
            brain.secret_path(old.id).is_file()):
        raise ValidationError("Este segredo tem valor. Apague o valor (na UI) antes de mudar o "
                              "tipo do item.")
    if record.type != "secret":
        return record
    if not record.key:
        raise ValidationError("segredo precisa de key (secret/<nome>): é por ela que o "
                              "knowledge-mcp run o encontra.")
    if clean.get("content") and clean["content"] != record.summary:
        raise ValidationError("segredo não tem corpo — só title e summary (para que serve). "
                              "O valor vai pela UI (fill_url).")
    if any(_looks_random(getattr(record, f)) for f in ("title", "summary")):
        raise ValidationError("o texto do segredo parece conter a credencial. Descreva só para "
                              "que serve; o valor vai pela UI (fill_url).")
    return dataclasses.replace(record, content=record.summary)


def cleanup_reason(record: ItemRecord, use: dict[str, Any] | None, now: datetime) -> str | None:
    """Por que o item é candidato à limpeza (None se não é)."""
    tags = record.tags or []
    if ARCHIVED_TAG in tags and record.updated_at <= now - timedelta(days=ARCHIVED_DAYS):
        return "archived"
    use = use or {}
    limit = now - timedelta(days=UNUSED_DAYS)
    last = _parse_ts(use.get("last_used_at"))
    opened = int(use.get("opened") or 0)
    if record.created_at <= limit and not opened and (last is None or last <= limit):
        return "unused"
    return None


def record_url(brain: Brain, record: ItemRecord) -> str:
    ref = SimpleNamespace(workspace_id=slugify(record.workspace or ""),
                          project_id=slugify(record.project or ""), id=record.id)
    return item_url(ref, brain.cid)


def result_dict(brain: Brain, hit: Hit, paths: list[str] | None,
                content_head: int | None) -> dict[str, Any]:
    """Resultado de busca: resumo explicado, nunca o `content` inteiro."""
    r = hit.record
    row: dict[str, Any] = {
        "id": r.id, "key": r.key, "type": r.type, "title": r.title,
        "summary": r.summary, "where": _where(r), "score": float(hit.score),
        "matched_in": list(hit.matched_in), "snippet": hit.snippet,
        "url": record_url(brain, r),
    }
    if paths:
        row["excerpt"] = hit.excerpt
    if content_head is not None:
        row["content_head"] = (r.content or "")[:max(0, int(content_head))]
    return row


def full_dict(brain: Brain, record: ItemRecord, now: datetime | None = None) -> dict[str, Any]:
    """O item completo como dicionário (o `item_get`)."""
    item = brain.view(record)
    row: dict[str, Any] = {
        "id": item.id, "key": item.key, "workspace": item.workspace, "project": item.project,
        "subject": item.subject, "where": _where(record), "type": item.type,
        "title": item.title, "summary": item.summary, "content": item.content,
        "tags": item.tags, "links": item.links, "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }
    row["url"] = item_url(item, brain.cid)
    if item.type == "secret":
        row["has_value"] = item.has_value
        row["fill_url"] = row["url"]
    return row


def location_names(snap: Snapshot, workspace: str,
                   project: str | None) -> tuple[str, str | None]:
    """Nomes de exibição do workspace/project (existentes por nome ou id; novos validados).
    Sem project (item que mora no workspace), devolve (workspace, None)."""
    ws = snap.find_workspace(workspace)
    ws_name = ws.name if ws else check_name(workspace, "workspace")
    if not project:
        return ws_name, None
    pj = snap.find_project(slugify(ws_name), project) if ws else None
    pj_name = pj.name if pj else check_name(project, "project")
    return ws_name, pj_name


def subject_name(snap: Snapshot, ws_name: str, pj_name: str, ref: str) -> str:
    """Nome do subject (existente por nome ou id; novo validado)."""
    found = snap.find_subject(slugify(ws_name), slugify(pj_name), ref)
    return found.name if found else check_name(ref, "subject")


def similar_in(snap: Snapshot, workspace_id: str, title: str, limit: int = SIMILAR_LIMIT,
               exclude: str | None = None) -> list[dict[str, Any]]:
    """Itens vigentes (não arquivados) do workspace com título parecido."""
    cands: Iterable[Candidate] = (
        Candidate(r) for r in snap.items_in(workspace_id)
        if r.id != exclude and ARCHIVED_TAG not in (r.tags or [])
    )
    hits = rank(cands, title, limit)
    return [{"id": h.record.id, "key": h.record.key, "title": h.record.title,
             "summary": h.record.summary} for h in hits]
