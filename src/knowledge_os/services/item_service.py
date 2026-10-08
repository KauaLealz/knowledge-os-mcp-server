"""Itens do segundo cérebro (v2): salvar em lote, ler, buscar, apagar e o retorno do agente.

Toda escrita monta um rascunho (`brain.Draft`) e publica de uma vez pelo repositório git da
conexão: em `review_mode="direct"` grava, comita (e empurra, se houver remote) e a leitura
seguinte já vê o resultado; em `review_mode="pr"` abre PR (ou Issue) e a pasta continua na
branch principal — a mudança só aparece depois do merge e de um sync.

Alcance: quem olha de um repositório ligado passa `viewpoint = (ws_id, pj_id)` (slugs); pasta
não ligada passa `None` e só enxerga os globais. Quem decide o que entra é `services.scope`
(a mesma cadeia para busca, `get_many`, `delete` e `feedback`).

Superfície pública (o que MCP, CLI/hook e API consomem):

- `save(items, default_location=None) -> list[dict]` — lote atômico de até 20 entradas
  (campos `model.ITEM_FIELDS` + `workspace, project, subject`). Por entrada:
  `{index, id, key, scope (efetivo), action: created|updated|unchanged, warnings, similar?,
  has_value?, fill_url?}`; em modo PR, `{index, id, key, status, pr_url|issue_url}`.
  `default_location` = (nome do workspace, nome do project) do repositório ligado.
- `get_many(keys=None, ids=None, viewpoint=None, workspace=None, project=None) -> list[dict]`
  — até 20; o item completo (com `content`, `where`, `scope` efetivo, `relations`) ou
  `{key|id, missing: True}`; soma `opened`.
- `search(query="", queries=None, viewpoint=None, workspace=None, everywhere=False, paths=None,
  types=None, subtypes=None, status=None, tags=None, origin=None, scope=None, limit=10,
  content_head=None) -> dict` — `{results}` | `{groups: [{query, results}]}` |
  `{groups: [{group, results}]}`; `suggestion` na pasta não ligada; soma `shown`.
- `delete(keys=None, ids=None, viewpoint=None, confirm=False) -> dict` — candidatos à limpeza,
  prévia ou remoção (com as relações que apontam para o item), num commit.
- `feedback(items, viewpoint=None, repo_path=None) -> dict` — `{applied, missing}`.
- Finos, para a API e o hook: `create(workspace_id, project_id, subject_id=None, **campos)`,
  `update(item_id, **campos)`, `get(item_id)`, `get_by_key(ws_id, pj_id, key)` (devolvem
  `brain.Item`), `remove(item_id) -> bool`, `similar(ws_id, title)`, `track_use(ids)`,
  `ensure_location(workspace, project)` e `resolve_{workspace,project,subject}_id`.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
import subprocess
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import (
    DEFAULT_ORIGIN,
    DEFAULT_STATUS,
    EXPIRED,
    ORIGINS,
    OUTCOMES,
    SCOPES,
    SPEC_STATUSES,
    STATUSES,
    TYPES,
    content_warnings,
    key_problem,
    key_warnings,
    statuses_for,
    validate_entry,
)
from knowledge_os.services import scope as scope_mod
from knowledge_os.services.brain import (
    Brain,
    Draft,
    Item,
    Snapshot,
    check_name,
    is_expired,
    meta_location,
    utcnow,
)
from knowledge_os.services.item_file import slugify
from knowledge_os.services.relation_service import review_fields
from knowledge_os.services.secret_guard import ensure_no_secrets
from knowledge_os.services.secret_service import fill_url
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
STALE_REVIEW_DAYS = 14
UNUSED_DAYS = 90
IRRELEVANT_MIN = 3
REASONS = ("expired", "archived_90d", "stale_review_14d", "irrelevant", "unused")

SUGGESTION = (
    "Pasta não ligada a um project: só os itens globais aparecem. Ligue com "
    'repo(action="link", repo=".", workspace="<workspace>", project="<project>").'
)

# Campos que trariam o valor de um segredo pelo agente: recusados no item_save.
VALUE_FIELDS = frozenset({"value", "valor", "secret_value", "secret", "token", "password",
                          "senha", "api_key", "apikey"})
# Palavra com cara de credencial aleatória (16+ caracteres, maiúscula, minúscula e dígito).
_RANDOM_WORD = re.compile(r"\S{16,}")
_TEXT_FIELDS = ("title", "summary", "content", "keywords")
# Campos da entrada que viram campo do arquivo (o resto é local ou identidade).
_RECORD_FIELDS = ("key", "type", "subtype", "scope", "title", "summary", "content", "status",
                  "tags", "links", "scope_paths", "ttl_days", "keywords", "source", "origin")

# Grupos do "essencial" (busca sem consulta, de um repositório ligado), nesta ordem.
GROUPS: tuple[tuple[str, Callable[[ItemRecord], bool]], ...] = (
    ("seguranca", lambda r: r.type == "rule" and r.subtype == "security"),
    ("regras", lambda r: r.type == "rule" and r.subtype != "security"),
    ("contexto", lambda r: r.type == "context"),
    ("specs", lambda r: r.type == "spec" and r.status in ("active", "draft")),
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


def signal_boost(record: ItemRecord, use: dict[str, Any] | None) -> float:
    """Peso dos sinais de uso no ranking (V2_MVP.md §5).

    `(1 + 0.1·ln(1 + helped + opened)) × (1 − 0.3·taxa_irrelevant)`, com
    `taxa_irrelevant = irrelevant / max(1, shown)` (no máximo 1); `origin=user` nunca perde peso.
    """
    use = use or {}
    helped, opened = int(use.get("helped") or 0), int(use.get("opened") or 0)
    rate = min(1.0, int(use.get("irrelevant") or 0) / max(1, int(use.get("shown") or 0)))
    penalty = 1 - 0.3 * rate
    if record.origin == "user":
        penalty = max(penalty, 1.0)
    return (1 + 0.1 * math.log(1 + helped + opened)) * penalty


def head_commit(repo_path: str | None) -> str | None:
    """`git rev-parse HEAD` do repositório de código (None se não houver, ou não for git)."""
    if not repo_path:
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", sha) else None


class ItemService:
    """Itens da conexão (a informada ou a padrão). Ver a docstring do módulo."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def brain(self) -> Brain:
        return Brain(self._connection_id)

    # ------------------------------------------------------------------ resolução

    def resolve_workspace_id(self, ref: str) -> str:
        """Resolve um workspace por nome ou id. Levanta NotFoundError se não existir."""
        return self.brain().snapshot.workspace(ref).id

    def resolve_project_id(self, workspace_id: str, ref: str) -> str:
        """Resolve um project (nome ou id) dentro do workspace. Levanta NotFoundError."""
        return self.brain().snapshot.project(workspace_id, ref).id

    def resolve_subject_id(self, workspace_id: str, project_id: str, ref: str) -> str:
        """Resolve um subject (nome ou id) dentro do project. Levanta NotFoundError."""
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
        """Grava até 20 itens numa publicação só; cada entrada escolhe o modo pelo que traz.

        - `key`: upsert no project (o da entrada ou `default_location`): cria ou atualiza o item
          que mora lá, sem duplicar.
        - `id`: atualiza esse item (só os campos informados); com `workspace`+`project` novos,
          move (o `subject`, se vier, vale no destino; senão o item fica sem subject); só
          `subject` troca o subject no project atual.
        - nenhum dos dois: cria e devolve `similar` (títulos parecidos no workspace).

        Valida por `model.validate_entry` (campo desconhecido, tipo, subtipo, status, scope,
        origin) usando, numa atualização parcial, o tipo do item. A key de um item existente não
        muda. Avisos: modelo do `content`, key fora do padrão (na criação), tag nova. Segredo:
        item `secret` com key e sem corpo (o valor é recusado e vai pela UI — `fill_url`);
        conteúdo com cara de segredo num item comum é recusado. Qualquer erro desfaz o lote e
        aponta a entrada (`Entrada i`).
        """
        entries = _batch(items, "itens")
        if not entries:
            return []
        for i, raw in enumerate(entries):
            if not isinstance(raw, dict):
                raise ValidationError(f"Entrada {i}: cada item deve ser um objeto")
            if VALUE_FIELDS & {str(k).lower() for k in raw}:
                raise ValidationError(
                    f"Entrada {i}: o valor de um segredo não passa pelo agente. Grave o item "
                    "(type secret) sem valor e passe ao usuário o fill_url da resposta: ele "
                    "preenche na UI local."
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
            if record is not None and record.type == "secret":
                item = brain.view(record)
                row["has_value"] = item.has_value
                row["fill_url"] = fill_url(item, brain.cid)
        return rows

    def _save_one(self, brain: Brain, d: Draft, raw: dict[str, Any],
                  default_location: tuple[str, str] | None) -> dict[str, Any]:
        item_id, key = raw.get("id"), raw.get("key")
        ws_ref, pj_ref = raw.get("workspace"), raw.get("project")
        if bool(ws_ref) != bool(pj_ref):
            raise ValidationError("informe workspace e project juntos (ou nenhum dos dois, para "
                                  "usar o project ligado ao repo)")
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
                existing = d.by_key(slugify(names[0]), slugify(names[1]), key)

        probe = dict(raw)
        if existing is not None and "type" not in probe:
            probe["type"] = existing.type  # subtipo e status valem pelo tipo do item
        clean, _ = validate_entry(probe)
        if existing is not None and "type" not in raw:
            clean.pop("type", None)
        ensure_no_secrets(**{f: clean.get(f) for f in _TEXT_FIELDS if f in clean})

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
        if action == "created" or {"type", "subtype", "content", "links"} & clean.keys():
            warnings += content_warnings(record.type, record.subtype, record.content,
                                         record.links)
        if clean.get("tags"):
            warnings += TagService.ensure_in_draft(d, clean["tags"])
        row: dict[str, Any] = {"id": record.id, "key": record.key,
                               "scope": d.effective_scope(record), "action": action,
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
            type=clean["type"], subtype=clean.get("subtype"), scope=clean.get("scope"),
            title=clean["title"], status=clean.get("status") or DEFAULT_STATUS,
            tags=sorted(clean.get("tags") or []), links=list(clean.get("links") or []),
            scope_paths=list(clean.get("scope_paths") or []), ttl_days=clean.get("ttl_days"),
            keywords=clean.get("keywords"), source=clean.get("source"),
            origin=clean.get("origin") or DEFAULT_ORIGIN, verified_at=None,
            verified_commit=None, created_at=now, updated_at=now, relations=[],
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
                "nome, crie um item novo e ligue com relation_create(type=\"supersedes\")"
            )
        changes: dict[str, Any] = {}
        for name in _RECORD_FIELDS:
            if name not in clean:
                continue
            value = clean[name]
            if name in ("status", "origin", "key") and value is None:
                continue
            if name == "tags":
                value = sorted(value)
            elif name == "content":
                value = value or ""
            if name == "ttl_days" and value is not None:
                changes[name] = value  # renovar conta a partir de agora, mesmo com o mesmo prazo
            elif getattr(existing, name) != value:
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
        return d.put(dataclasses.replace(record, updated_at=utcnow())), "updated"

    # ------------------------------------------------------------------ leitura

    def get(self, item_id: str) -> Item:
        """O item completo (`brain.Item`). NotFoundError se não existir."""
        brain = self.brain()
        return brain.view(brain.snapshot.require(item_id))

    def get_by_key(self, workspace_id: str, project_id: str, key: str) -> Item:
        """Item de `key` no workspace/project (slugs). Levanta NotFoundError."""
        brain = self.brain()
        record = brain.snapshot.by_key(workspace_id, project_id, key)
        if record is None:
            raise NotFoundError(f"Item não encontrado: key {key!r}")
        return brain.view(record)

    def get_many(self, keys: list[str] | None = None, ids: list[str] | None = None,
                 viewpoint: scope_mod.Viewpoint = None, workspace: str | None = None,
                 project: str | None = None) -> list[dict[str, Any]]:
        """Até 20 itens completos, na ordem pedida (keys, depois ids); soma `opened`.

        A key é resolvida pela cadeia de alcance de `viewpoint` (`scope.resolve_key`) ou, com
        `workspace`+`project`, só nesse project. Faltando: `{key|id, missing: True}`.
        """
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
                record = scope_mod.resolve_key(snap, ref, viewpoint)
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
        viewpoint: scope_mod.Viewpoint = None,
        workspace: str | None = None,
        everywhere: bool = False,
        paths: list[str] | None = None,
        types: list[str] | str | None = None,
        subtypes: list[str] | str | None = None,
        status: list[str] | str | None = None,
        tags: list[str] | None = None,
        origin: list[str] | str | None = None,
        scope: list[str] | str | None = None,
        limit: int = 10,
        content_head: int | None = None,
    ) -> dict[str, Any]:
        """Busca explicada pela cadeia de alcance (V2_MVP.md §5); nunca devolve o `content`.

        Pool: `everywhere=True` → tudo (distância 1.0); `workspace=` → o workspace inteiro
        (qualquer scope, 1.0) + os globais de fora (0.7); senão `scope.reach(viewpoint)`.
        Padrão exclui `archived` e vencidos (`status=["expired"]` os mostra); `review` entra,
        com peso menor e marcado. `paths` sobe quem casa `scope_paths` (com `excerpt`) e, sem
        consulta, tira quem tem `scope_paths` de outro lugar. Com `queries` (até 5):
        `{groups: [{query, results}]}`. Sem consulta, de um repositório ligado e sem filtros: o
        essencial em `{groups: [{group, results}]}` (`seguranca`, `regras`, `contexto`, `specs`).
        Pasta não ligada leva `suggestion`. Soma `shown` em cada resultado devolvido;
        consulta que volta vazia vai para `searches/<conn>.jsonl`. `content_head=N` inclui os
        N primeiros caracteres do `content` em cada resultado (para o pacote do hook).
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
        subtype_set = _choices("subtypes", subtypes,
                               tuple(dict.fromkeys(s for subs in TYPES.values() for s in subs)))
        status_set = _choices("status", status, STATUSES + SPEC_STATUSES + (EXPIRED,))
        origin_set = _choices("origin", origin, ORIGINS)
        scope_set = _choices("scope", scope, SCOPES)
        tag_list = _texts("tags", tags)

        brain = self.brain()
        snap = brain.snapshot
        now = utcnow()

        browsing = not query.strip() and not queries

        def wanted(r: ItemRecord) -> bool:
            shown_status = EXPIRED if is_expired(r, now) else r.status
            if status_set is None:
                if shown_status in ("archived", EXPIRED):
                    return False
            elif shown_status not in status_set:
                return False
            if type_set and r.type not in type_set:
                return False
            if subtype_set and r.subtype not in subtype_set:
                return False
            if origin_set and r.origin not in origin_set:
                return False
            if scope_set and snap.effective_scope(r) not in scope_set:
                return False
            if tag_list and not set(tag_list) <= set(r.tags or []):
                return False
            # Sem consulta (navegar pela área), `paths` tira o que tem escopo de outro lugar; com
            # consulta só ordena: um item achado pelo texto não some por ter escopo em outra pasta.
            return not (browsing and paths and r.scope_paths and not paths_match(r, paths))

        usage = brain.usage()
        cands = [Candidate(r, dist, signal_boost(r, usage.get(r.id)))
                 for r, dist in self._pool(snap, viewpoint, workspace, everywhere) if wanted(r)]
        shown: list[str] = []

        def run(text: str, pool: list[Candidate]) -> list[dict[str, Any]]:
            hits = rank(pool, text, limit, index=brain.store.index, paths=paths)
            if text and not hits:
                local_state.log_empty_search(brain.cid, text)
            shown.extend(h.record.id for h in hits)
            return [result_dict(snap, h, now, paths, content_head) for h in hits]

        filtered = any(v is not None for v in (paths, type_set, subtype_set, status_set,
                                                origin_set, scope_set, tag_list))
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
    def _pool(snap: Snapshot, viewpoint: scope_mod.Viewpoint, workspace: str | None,
              everywhere: bool) -> list[tuple[ItemRecord, float]]:
        if everywhere:
            return [(r, scope_mod.SAME_PROJECT) for r in snap.records.values()]
        if workspace:
            ws = snap.find_workspace(workspace)
            if ws is None:
                known = ", ".join(w.name for w in snap.workspaces()) or "(nenhum)"
                raise NotFoundError(f"Workspace não encontrado: {workspace}. Existentes: {known}")
            pool = []
            for r in snap.records.values():
                if slugify(r.workspace or "") == ws.id:
                    pool.append((r, scope_mod.SAME_PROJECT))
                elif snap.effective_scope(r) == "global":
                    pool.append((r, scope_mod.ELSEWHERE))
            return pool
        return scope_mod.reach(snap, viewpoint)

    def similar(self, workspace_id: str, title: str, limit: int = SIMILAR_LIMIT,
                ) -> list[dict[str, Any]]:
        """Itens vigentes do workspace com título parecido (para avisar antes de duplicar)."""
        return similar_in(self.brain().snapshot, workspace_id, title, limit)

    def track_use(self, ids: list[str]) -> None:
        """Conta uma abertura (`opened`) de cada item; nunca derruba a leitura."""
        if ids:
            self.brain().count(ids, "opened")

    # ------------------------------------------------------------------ delete

    def delete(self, keys: list[str] | None = None, ids: list[str] | None = None,
               viewpoint: scope_mod.Viewpoint = None, confirm: bool = False) -> dict[str, Any]:
        """Limpeza em três passos (V2_MVP.md §6).

        - Sem `keys`/`ids`: `{candidates: [{key, id, reason}]}` no alcance de `viewpoint`
          (sem viewpoint, a conexão inteira), `reason` ∈ `expired`, `archived_90d`,
          `stale_review_14d`, `irrelevant`, `unused`; nunca `origin=user`.
        - Com `keys`/`ids` (até 20) e sem `confirm`: `{status: "preview", items, missing?}`.
        - `confirm=True`: apaga os itens (e o valor de um segredo) e tira as relações que
          apontam para eles, num commit: `{status: "deleted", ids, missing?}`; em modo PR,
          `{ids, status: pending_review|issue_opened, pr_url|issue_url}`.
        """
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
                record = (d.get(ref) if kind == "id"
                          else scope_mod.resolve_key(d, ref, viewpoint))
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
                          "where": scope_mod.where(r), "relations_in": incoming.get(r.id, 0)}
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
        """Apaga um item pelo id (API). NotFoundError se não existir; False em modo PR."""
        result = self.delete(ids=[item_id], confirm=True)
        if result.get("missing"):
            raise NotFoundError(f"Item não encontrado: {item_id}")
        return result.get("status") == "deleted"

    @staticmethod
    def _candidates(brain: Brain, viewpoint: scope_mod.Viewpoint) -> list[dict[str, Any]]:
        snap = brain.snapshot
        now = utcnow()
        usage = brain.usage()
        records = ([r for r, _ in scope_mod.reach(snap, viewpoint)] if viewpoint is not None
                   else list(snap.records.values()))
        out = []
        for record in records:
            reason = cleanup_reason(record, usage.get(record.id), now)
            if reason:
                out.append({"key": record.key, "id": record.id, "reason": reason})
        out.sort(key=lambda c: (REASONS.index(c["reason"]), c["key"] or "", c["id"]))
        return out

    # ------------------------------------------------------------------ feedback

    def feedback(self, items: list[dict[str, Any]], viewpoint: scope_mod.Viewpoint = None,
                 repo_path: str | None = None) -> dict[str, Any]:
        """O agente diz o que o item fez por ele: `[{key|id, outcome, note?, query?}]` (até 20).

        Todo outcome soma o contador local de mesmo nome (`usage/<conn>.json`, fora do git).
        `helped`/`irrelevant` param aí. `wrong`/`outdated` põem o item em `review` e anexam a
        `note` ao `content` (`> Revisão <data>: <nota>`), com commit. `verified` grava
        `verified_at` (agora) e `verified_commit` (`git rev-parse HEAD` de `repo_path`; ausente
        se não houver), sem reativar item em `review`. Key/id que não se resolve vai para
        `missing`. Retorno: `{applied, missing}` (+ `status`/`pr_url` em modo PR).
        """
        entries = _batch(items, "itens")
        for i, e in enumerate(entries):
            if not isinstance(e, dict) or not (e.get("key") or e.get("id")):
                raise ValidationError(f"items[{i}]: use {{\"key\": ..., \"outcome\": ...}} "
                                      "(ou id no lugar de key)")
            if e.get("outcome") not in OUTCOMES:
                raise ValidationError(f"items[{i}]: outcome inválido: {e.get('outcome')!r}. "
                                      f"Válidos: {', '.join(OUTCOMES)}")
            note = e.get("note")
            if note is not None and not isinstance(note, str):
                raise ValidationError(f"items[{i}]: note deve ser texto")
            ensure_no_secrets(note=note)
        brain = self.brain()
        applied = 0
        missing: list[str] = []
        counted: dict[str, list[str]] = {}
        commit_sha: list[str | None] = []  # calculado uma vez, só se algum `verified` pedir
        now = utcnow()
        with brain.editing() as d:
            for e in entries:
                ref = e.get("key") or e.get("id")
                record = (scope_mod.resolve_key(d, ref, viewpoint) if e.get("key")
                          else d.get(ref))
                if record is None:
                    missing.append(ref)
                    continue
                applied += 1
                outcome = e["outcome"]
                counted.setdefault(outcome, []).append(record.id)
                current = d.require(record.id)
                if outcome in ("wrong", "outdated"):
                    changes: dict[str, Any] = {}
                    if current.status != "review":
                        changes["status"] = "review"
                    note = " ".join((e.get("note") or "").split())
                    if note:
                        changes["content"] = (f"{current.content.rstrip()}\n\n"
                                              f"> Revisão {now.date().isoformat()}: {note}\n")
                    if changes:
                        d.update(record.id, **changes, updated_at=now)
                elif outcome == "verified":
                    if not commit_sha:
                        commit_sha.append(head_commit(repo_path))
                    d.update(record.id, verified_at=now, verified_commit=commit_sha[0],
                             updated_at=now)
            publish = brain.commit(d, f"knowledge-os: feedback em {applied} item(ns)")
        for field, record_ids in counted.items():
            brain.count(record_ids, field)
        return {"applied": applied, "missing": missing, **review_fields(publish)}

    # ------------------------------------------------------------------ finos (API, hook)

    def create(self, workspace_id: str, project_id: str, subject_id: str | None = None,
               **fields: Any) -> Item:
        """Cria um item (campos de `model.ITEM_FIELDS`) e devolve o `brain.Item`."""
        entry = {"workspace": workspace_id, "project": project_id, **fields}
        if subject_id:
            entry["subject"] = subject_id
        return self._saved(self.save([entry])[0])

    def update(self, item_id: str, **fields: Any) -> Item:
        """Atualiza só os campos informados (tags substituem as atuais)."""
        return self._saved(self.save([{"id": item_id, **fields}])[0])

    def _saved(self, row: dict[str, Any]) -> Item:
        if "action" not in row:  # modo PR: só existe depois do merge
            raise ValidationError(f"Mudança aguardando revisão: {row.get('pr_url') or row}")
        return self.get(row["id"])


# --------------------------------------------------------------------------- helpers


def _checked(brain: Brain, record: ItemRecord, old: ItemRecord | None,
             clean: dict[str, Any]) -> ItemRecord:
    """Regras que cruzam campos, sobre o item já mesclado (criação ou atualização)."""
    valid_subtypes = TYPES[record.type]
    if record.subtype and record.subtype not in valid_subtypes:
        if not valid_subtypes:
            raise ValidationError(f"{record.type} não tem subtipo: remova subtype")
        raise ValidationError(f"subtype {record.subtype!r} não serve para {record.type}. "
                              f"Válidos: {', '.join(valid_subtypes)} (ou subtype: null)")
    if record.status not in statuses_for(record.type):
        raise ValidationError(f"status {record.status!r} não serve para {record.type}. "
                              f"Válidos: {', '.join(statuses_for(record.type))}")
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
    if any(_looks_random(getattr(record, f)) for f in ("title", "summary", "keywords")):
        raise ValidationError("o texto do segredo parece conter a credencial. Descreva só para "
                              "que serve; o valor vai pela UI (fill_url).")
    return dataclasses.replace(record, content=record.summary)  # o resumo diz para que serve


def cleanup_reason(record: ItemRecord, use: dict[str, Any] | None, now: datetime) -> str | None:
    """Por que o item é candidato à limpeza (None se não é). `origin=user` nunca é."""
    if record.origin == "user":
        return None
    if is_expired(record, now):
        return "expired"
    if record.status == "archived" and record.updated_at <= now - timedelta(days=ARCHIVED_DAYS):
        return "archived_90d"
    if record.status == "review" and record.updated_at <= now - timedelta(
            days=STALE_REVIEW_DAYS):
        return "stale_review_14d"
    if record.origin != "agent":
        return None
    use = use or {}
    irrelevant, helped = int(use.get("irrelevant") or 0), int(use.get("helped") or 0)
    if irrelevant >= IRRELEVANT_MIN and irrelevant > helped:
        return "irrelevant"
    limit = now - timedelta(days=UNUSED_DAYS)
    last = _parse_ts(use.get("last_used_at"))
    if record.created_at <= limit and (last is None or last <= limit):
        return "unused"
    return None


def result_dict(snap: Snapshot, hit: Hit, now: datetime, paths: list[str] | None,
                content_head: int | None) -> dict[str, Any]:
    """Resultado de busca: resumo explicado, nunca o `content` inteiro."""
    r = hit.record
    row: dict[str, Any] = {
        "id": r.id, "key": r.key, "type": r.type, "subtype": r.subtype, "title": r.title,
        "summary": r.summary, "scope": snap.effective_scope(r), "where": scope_mod.where(r),
        "status": EXPIRED if is_expired(r, now) else r.status, "score": float(hit.score),
        "matched_in": list(hit.matched_in), "snippet": hit.snippet,
    }
    if paths:
        row["excerpt"] = hit.excerpt
        row["scope_paths"] = list(r.scope_paths or [])
    if content_head is not None:
        row["content_head"] = (r.content or "")[:max(0, int(content_head))]
    return row


def full_dict(brain: Brain, record: ItemRecord, now: datetime | None = None) -> dict[str, Any]:
    """O item completo como dicionário (o `item_get`)."""
    snap = brain.snapshot
    item = brain.view(record)
    relations = []
    for rel in snap.relations_of(record):
        target = snap.require(rel.target_item_id)
        relations.append({"type": rel.relation_type, "target": target.key or target.id,
                          "target_id": target.id})
    row: dict[str, Any] = {
        "id": item.id, "key": item.key, "workspace": item.workspace, "project": item.project,
        "subject": item.subject, "where": scope_mod.where(record), "type": item.type,
        "subtype": item.subtype, "scope": item.effective_scope, "scope_explicit": item.scope,
        "title": item.title, "summary": item.summary, "content": item.content,
        "status": EXPIRED if is_expired(record, now) else item.status, "tags": item.tags,
        "links": item.links, "scope_paths": item.scope_paths, "ttl_days": item.ttl_days,
        "expires_at": _iso(item.expires_at), "keywords": item.keywords, "source": item.source,
        "origin": item.origin, "verified_at": _iso(item.verified_at),
        "verified_commit": item.verified_commit, "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at), "relations": relations,
    }
    if item.type == "secret":
        row["has_value"] = item.has_value
        row["fill_url"] = fill_url(item, brain.cid)
    return row


def location_names(snap: Snapshot, workspace: str, project: str) -> tuple[str, str]:
    """Nomes de exibição do workspace/project (existentes por nome ou id; novos validados)."""
    ws = snap.find_workspace(workspace)
    ws_name = ws.name if ws else check_name(workspace, "workspace")
    pj = snap.find_project(slugify(ws_name), project) if ws else None
    pj_name = pj.name if pj else check_name(project, "project")
    return ws_name, pj_name


def subject_name(snap: Snapshot, ws_name: str, pj_name: str, ref: str) -> str:
    """Nome do subject (existente por nome ou id; novo validado)."""
    found = snap.find_subject(slugify(ws_name), slugify(pj_name), ref)
    return found.name if found else check_name(ref, "subject")


def similar_in(snap: Snapshot, workspace_id: str, title: str, limit: int = SIMILAR_LIMIT,
               exclude: str | None = None) -> list[dict[str, Any]]:
    """Itens vigentes (não arquivados nem vencidos) do workspace com título parecido."""
    now = utcnow()
    cands: Iterable[Candidate] = (
        Candidate(r) for r in snap.items_in(workspace_id)
        if r.id != exclude and r.status != "archived" and not is_expired(r, now)
    )
    hits = rank(cands, title, limit)
    return [{"id": h.record.id, "key": h.record.key, "title": h.record.title,
             "summary": h.record.summary} for h in hits]
