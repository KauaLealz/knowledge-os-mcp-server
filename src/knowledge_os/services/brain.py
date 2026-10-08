"""O segundo cérebro de uma conexão, lido e gravado só nos arquivos da pasta dela.

Modelo em disco (a pasta é um repositório git):

- Item: `<workspace>/<project>/<key>.md` (ou `_sem-key/<id>.md`), frontmatter YAML com os nomes
  de workspace/project/subject, tags, labels e relações (`services.item_file`).
- Workspace, project e subject existem pelos itens que os citam ou por um `.knowledge.yaml`:
  na pasta do workspace (`name`, `description`), na do project (`name`, `description`,
  `subjects: [...]`). Tags e labels criadas sem item ficam no `.knowledge.yaml` da raiz.

Ids: workspace, project e subject têm como id o slug do nome (`item_file.slugify`), que é
também o nome da pasta; o id do project vale dentro do workspace e o do subject dentro do
project. Itens mantêm o UUID do frontmatter. Relação: id derivado de (origem, tipo, alvo).

`Snapshot` é a leitura de um momento (itens + `.knowledge.yaml`); `Draft` acumula mudanças em
memória e vira, de uma vez, o conjunto de arquivos a gravar/remover; `Brain.commit` publica
esse conjunto pelo repositório git da conexão (direto ou por PR) numa publicação só.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from knowledge_os.config import ConnectionConfig
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.git_repo_service import PublishResult
from knowledge_os.services.item_file import id_problem, safe_join, slugify
from knowledge_os.storage import local_state
from knowledge_os.storage.access import (
    folder_lock,
    git_for,
    lock_for,
    resolve_connection,
    store_for,
)
from knowledge_os.storage.files import ItemRecord, record_text

logger = logging.getLogger(__name__)

META_FILE = ".knowledge.yaml"
SECRETS_DIRNAME = ".secrets"  # pasta da conexão onde o valor cifrado mora (fora do git)
DEFAULT_LABELS = ("official", "critical", "experimental", "deprecated", "reference")
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_RELATION_NS = uuid.UUID("5b0f7a8e-3c1d-4f6a-9e2b-7d4c8a1f0e93")
_editing = threading.local()  # conexões cuja trava entre processos esta thread já tem


def utcnow() -> datetime:
    """Agora em UTC, sem tzinfo e sem microssegundos (o formato gravado nos arquivos)."""
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def relation_id(source_id: str, relation_type: str, target_id: str) -> str:
    """Id estável de uma relação (não há onde guardar um id sorteado)."""
    return str(uuid.uuid5(_RELATION_NS, f"{source_id}|{relation_type}|{target_id}"))


def expires_at(record: ItemRecord) -> datetime | None:
    """Vencimento de um ephemeral: `updated_at` + `ttl_days` (None nas outras classes)."""
    if record.memory_class != "ephemeral" or not record.ttl_days:
        return None
    return record.updated_at + timedelta(days=int(record.ttl_days))


def is_expired(record: ItemRecord, now: datetime | None = None) -> bool:
    end = expires_at(record)
    return end is not None and end <= (now or utcnow())


def is_published(result: PublishResult | None) -> bool:
    """A mudança já vale na pasta? (direto, ou nada a publicar). Em PR/Issue, só depois do
    merge: estado local (`.secrets/*.enc`, `repos.json`) não pode mudar antes disso."""
    return result is None or result.status == "published"


def check_name(name: str | None, what: str) -> str:
    """Nome de workspace/project/subject: não vazio e com slug (vira nome de pasta)."""
    name = (name or "").strip()
    if not name or len(name) > 255:
        raise ValidationError(f"Nome de {what} deve ter de 1 a 255 caracteres")
    if not slugify(name) or slugify(name).startswith((".", "_")):
        raise ValidationError(f"Nome de {what} inválido: {name!r}")
    return name


# --------------------------------------------------------------------------- modelos


@dataclass
class Workspace:
    id: str
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Project:
    id: str
    workspace_id: str
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Subject:
    id: str
    project_id: str
    workspace_id: str
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Tag:
    id: str
    name: str


Label = Tag


@dataclass
class Relation:
    id: str
    source_item_id: str
    target_item_id: str
    relation_type: str
    created_at: datetime | None = None


@dataclass
class Item:
    """Item como os serviços o devolvem: o arquivo + ids, vencimento, uso e `has_value`."""

    id: str
    key: str | None
    workspace_id: str
    project_id: str
    subject_id: str | None
    workspace: str
    project: str
    subject: str | None
    type: str
    title: str
    summary: str
    content: str
    status: str
    memory_class: str
    tags: list[str]
    labels: list[str]
    scope_paths: list[str]
    confidence: int | None
    importance: int | None
    ttl_days: int | None
    keywords: str | None
    source: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    path: str
    access_count: int = 0
    last_accessed: datetime | None = None
    has_value: bool = False


# --------------------------------------------------------------------------- leitura


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_LOADER)  # noqa: S506
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        logger.warning("Ignorando %s inválido: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _visible_dirs(folder: Path) -> list[os.DirEntry[str]]:
    try:
        return [
            e for e in os.scandir(folder)
            if not e.name.startswith((".", "_")) and e.is_dir(follow_symlinks=False)
        ]
    except OSError:
        return []


def read_metas(root: Path) -> dict[str, dict[str, Any]]:
    """Todos os `.knowledge.yaml` (raiz, workspaces e projects), por path relativo."""
    metas: dict[str, dict[str, Any]] = {}
    if (root / META_FILE).is_file():
        metas[META_FILE] = _load_yaml(root / META_FILE)
    for ws in _visible_dirs(root):
        ws_path = Path(ws.path)
        if (ws_path / META_FILE).is_file():
            metas[f"{ws.name}/{META_FILE}"] = _load_yaml(ws_path / META_FILE)
        for pj in _visible_dirs(ws_path):
            if (Path(pj.path) / META_FILE).is_file():
                metas[f"{ws.name}/{pj.name}/{META_FILE}"] = _load_yaml(Path(pj.path) / META_FILE)
    return metas


def dump_meta(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def meta_location(ws_id: str | None = None, pj_id: str | None = None) -> str:
    """Path do `.knowledge.yaml`: da raiz, do workspace ou do project."""
    parts = [p for p in (ws_id, pj_id) if p]
    return "/".join([*parts, META_FILE])


def _subject_entries(raw: Any) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for entry in raw or []:
        if isinstance(entry, str) and entry.strip():
            out.append((entry.strip(), None))
        elif isinstance(entry, dict) and str(entry.get("name") or "").strip():
            out.append((str(entry["name"]).strip(), entry.get("description")))
    return out


@dataclass
class _Node:
    id: str
    name: str
    description: str | None = None
    named: bool = False  # nome vindo do `.knowledge.yaml` (vale sobre o dos itens)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    children: dict[str, _Node] = field(default_factory=dict)

    def touch(self, record: ItemRecord) -> None:
        if self.created_at is None or record.created_at < self.created_at:
            self.created_at = record.created_at
        if self.updated_at is None or record.updated_at > self.updated_at:
            self.updated_at = record.updated_at


def _names_from_meta(node: _Node, data: dict[str, Any]) -> None:
    name = str(data.get("name") or "").strip()
    if name:
        node.name, node.named = name, True
    if data.get("description") is not None:
        node.description = data.get("description")


class Snapshot:
    """Itens e `.knowledge.yaml` de uma conexão num momento, com as consultas do domínio."""

    def __init__(self, records: dict[str, ItemRecord], metas: dict[str, dict[str, Any]]) -> None:
        self.records = records
        self.metas = metas
        self._tree: dict[str, _Node] | None = None
        self._keys: dict[tuple[str, str, str], ItemRecord] | None = None

    def _invalidate(self) -> None:
        self._tree = None
        self._keys = None

    # ------------------------------------------------------------------ árvore

    @property
    def tree(self) -> dict[str, _Node]:
        if self._tree is None:
            self._tree = self._build_tree()
        return self._tree

    def _build_tree(self) -> dict[str, _Node]:
        tree: dict[str, _Node] = {}
        for rel, data in sorted(self.metas.items()):
            parts = rel.split("/")[:-1]
            if not parts:
                continue
            ws = tree.setdefault(parts[0], _Node(parts[0], parts[0]))
            if len(parts) == 1:
                _names_from_meta(ws, data)
                continue
            pj = ws.children.setdefault(parts[1], _Node(parts[1], parts[1]))
            _names_from_meta(pj, data)
            for name, description in _subject_entries(data.get("subjects")):
                sj = pj.children.setdefault(slugify(name), _Node(slugify(name), name))
                sj.named = True
                if description is not None:
                    sj.description = description
        for record in sorted(self.records.values(), key=lambda r: (r.created_at, r.path)):
            if not record.workspace or not record.project:
                continue
            ws_id, pj_id = slugify(record.workspace), slugify(record.project)
            ws = tree.get(ws_id)
            if ws is None:
                ws = tree[ws_id] = _Node(ws_id, record.workspace, named=True)
            elif not ws.named:
                ws.name, ws.named = record.workspace, True
            pj = ws.children.get(pj_id)
            if pj is None:
                pj = ws.children[pj_id] = _Node(pj_id, record.project, named=True)
            elif not pj.named:
                pj.name, pj.named = record.project, True
            ws.touch(record)
            pj.touch(record)
            if record.subject:
                sj_id = slugify(record.subject)
                sj = pj.children.get(sj_id)
                if sj is None:
                    sj = pj.children[sj_id] = _Node(sj_id, record.subject, named=True)
                sj.touch(record)
        return tree

    # ------------------------------------------------------------------ workspaces

    @staticmethod
    def _match(nodes: dict[str, _Node], ref: str | None) -> _Node | None:
        if not ref:
            return None
        ref = ref.strip()
        if ref in nodes:
            return nodes[ref]
        for node in nodes.values():
            if node.name == ref:
                return node
        return nodes.get(slugify(ref))

    def workspaces(self) -> list[Workspace]:
        return sorted(
            (self._workspace(n) for n in self.tree.values()), key=lambda w: w.name.casefold()
        )

    @staticmethod
    def _workspace(node: _Node) -> Workspace:
        return Workspace(node.id, node.name, node.description, node.created_at, node.updated_at)

    def find_workspace(self, ref: str | None) -> Workspace | None:
        node = self._match(self.tree, ref)
        return self._workspace(node) if node else None

    def workspace(self, ref: str) -> Workspace:
        found = self.find_workspace(ref)
        if found is None:
            raise NotFoundError(f"Workspace não encontrado: {ref}")
        return found

    # ------------------------------------------------------------------ projects

    def _ws_node(self, ws_ref: str) -> _Node:
        node = self._match(self.tree, ws_ref)
        if node is None:
            raise NotFoundError(f"Workspace não encontrado: {ws_ref}")
        return node

    @staticmethod
    def _project(ws: _Node, node: _Node) -> Project:
        return Project(node.id, ws.id, node.name, node.description, node.created_at,
                       node.updated_at)

    def projects(self, ws_ref: str) -> list[Project]:
        ws = self._ws_node(ws_ref)
        return sorted((self._project(ws, n) for n in ws.children.values()),
                      key=lambda p: p.name.casefold())

    def all_projects(self) -> list[Project]:
        return [p for ws in self.workspaces() for p in self.projects(ws.id)]

    def find_project(self, ws_ref: str, ref: str | None) -> Project | None:
        ws = self._match(self.tree, ws_ref)
        if ws is None:
            return None
        node = self._match(ws.children, ref)
        return self._project(ws, node) if node else None

    def project(self, ws_ref: str, ref: str) -> Project:
        self._ws_node(ws_ref)
        found = self.find_project(ws_ref, ref)
        if found is None:
            raise NotFoundError(f"Project não encontrado: {ref}")
        return found

    # ------------------------------------------------------------------ subjects

    @staticmethod
    def _subject(ws: _Node, pj: _Node, node: _Node) -> Subject:
        return Subject(node.id, pj.id, ws.id, node.name, node.description, node.created_at,
                       node.updated_at)

    def subjects(self, ws_ref: str, pj_ref: str) -> list[Subject]:
        ws = self._ws_node(ws_ref)
        pj = self._match(ws.children, pj_ref)
        if pj is None:
            raise NotFoundError(f"Project não encontrado: {pj_ref}")
        return sorted((self._subject(ws, pj, n) for n in pj.children.values()),
                      key=lambda s: s.name.casefold())

    def find_subject(self, ws_ref: str, pj_ref: str, ref: str | None) -> Subject | None:
        ws = self._match(self.tree, ws_ref)
        pj = self._match(ws.children, pj_ref) if ws else None
        node = self._match(pj.children, ref) if pj else None
        return self._subject(ws, pj, node) if node else None  # type: ignore[arg-type]

    def subject(self, ws_ref: str, pj_ref: str, ref: str) -> Subject:
        self.project(ws_ref, pj_ref)
        found = self.find_subject(ws_ref, pj_ref, ref)
        if found is None:
            raise NotFoundError(f"Subject não encontrado: {ref}")
        return found

    # ------------------------------------------------------------------ itens

    def get(self, item_id: str) -> ItemRecord | None:
        return self.records.get(item_id)

    def require(self, item_id: str) -> ItemRecord:
        record = self.records.get(item_id)
        if record is None:
            raise NotFoundError(f"Item não encontrado: {item_id}")
        return record

    def items_in(
        self, ws_id: str | None = None, pj_id: str | None = None, sj_id: str | None = None
    ) -> list[ItemRecord]:
        out = []
        for r in self.records.values():
            if ws_id is not None and slugify(r.workspace or "") != ws_id:
                continue
            if pj_id is not None and slugify(r.project or "") != pj_id:
                continue
            if sj_id is not None and slugify(r.subject or "") != sj_id:
                continue
            out.append(r)
        return out

    def by_key(self, ws_id: str, pj_id: str, key: str) -> ItemRecord | None:
        if self._keys is None:
            self._keys = {
                (slugify(r.workspace or ""), slugify(r.project or ""), r.key): r
                for r in self.records.values() if r.key
            }
        return self._keys.get((ws_id, pj_id, key))

    # ------------------------------------------------------------------ tags e labels

    def _root_names(self, kind: str) -> list[str]:
        raw = self.metas.get(META_FILE, {}).get(kind) or []
        return [str(n).strip() for n in raw if str(n).strip()]

    def tags(self) -> list[Tag]:
        names = set(self._root_names("tags"))
        for r in self.records.values():
            names.update(r.tags or [])
        return [Tag(n, n) for n in sorted(names)]

    def labels(self) -> list[Label]:
        removed = set(self._root_names("labels_removed"))
        names = {n for n in DEFAULT_LABELS if n not in removed}
        names.update(self._root_names("labels"))
        for r in self.records.values():
            names.update(r.labels or [])
        return [Label(n, n) for n in sorted(names)]

    # ------------------------------------------------------------------ relações

    def resolve_target(self, source: ItemRecord, ref: str) -> ItemRecord | None:
        """Alvo de uma relação: pelo id, ou pela key no mesmo workspace/project da origem."""
        found = self.records.get(ref)
        if found is not None:
            return found
        return self.by_key(slugify(source.workspace or ""), slugify(source.project or ""), ref)

    def relations_of(self, record: ItemRecord) -> list[Relation]:
        out = []
        for rel in record.relations or []:
            target = self.resolve_target(record, str(rel.get("target") or ""))
            rtype = str(rel.get("type") or "")
            if target is None or not rtype:
                continue
            out.append(Relation(relation_id(record.id, rtype, target.id), record.id, target.id,
                                rtype))
        return out

    def relations(self) -> list[Relation]:
        return [rel for r in self.records.values() for rel in self.relations_of(r)]

    def relation(self, relation_id_: str) -> Relation:
        for rel in self.relations():
            if rel.id == relation_id_:
                return rel
        raise NotFoundError(f"Relação não encontrada: {relation_id_}")


# --------------------------------------------------------------------------- escrita


@dataclass
class _Link:
    type: str
    target_id: str | None  # None: alvo que não se resolve (mantido como veio)
    raw: dict[str, str]


class Draft(Snapshot):
    """Mudanças em memória sobre um `Snapshot`; `files()` diz o que gravar e o que remover."""

    def __init__(self, base: Snapshot) -> None:
        super().__init__(dict(base.records), {k: dict(v) for k, v in base.metas.items()})
        self._base = base
        self._links: dict[str, list[_Link]] = {
            r.id: self._links_of(base, r) for r in base.records.values()
        }

    @staticmethod
    def _links_of(snapshot: Snapshot, record: ItemRecord) -> list[_Link]:
        out = []
        for raw in record.relations or []:
            target = snapshot.resolve_target(record, str(raw.get("target") or ""))
            out.append(_Link(str(raw.get("type") or ""), target.id if target else None,
                             dict(raw)))
        return out

    # ------------------------------------------------------------------ itens

    def put(self, record: ItemRecord) -> ItemRecord:
        self.records[record.id] = record
        self._links.setdefault(record.id, self._links_of(self, record))
        self._invalidate()
        return record

    def update(self, record_id: str, **changes: Any) -> ItemRecord:
        return self.put(dataclasses.replace(self.require(record_id), **changes))

    def remove(self, record_id: str) -> None:
        self.records.pop(record_id, None)
        self._links.pop(record_id, None)
        self._invalidate()

    # ------------------------------------------------------------------ relações

    def links(self, record_id: str) -> list[_Link]:
        return self._links.setdefault(record_id, [])

    def add_link(self, source_id: str, relation_type: str, target_id: str) -> bool:
        """Liga origem → alvo. False se a relação já existia."""
        links = self.links(source_id)
        if any(lk.type == relation_type and lk.target_id == target_id for lk in links):
            return False
        links.append(_Link(relation_type, target_id, {}))
        return True

    def drop_link(self, source_id: str, relation_type: str, target_id: str) -> bool:
        links = self.links(source_id)
        kept = [lk for lk in links
                if not (lk.type == relation_type and lk.target_id == target_id)]
        self._links[source_id] = kept
        return len(kept) != len(links)

    def _encode_links(self) -> None:
        """Regrava o `relations` de cada item a partir dos alvos resolvidos.

        Alvo no mesmo workspace/project e com key: pela key; senão pelo id. Alvo removido
        neste rascunho: a relação sai. Alvo que já não se resolvia: fica como estava.
        """
        for record_id in list(self.records):
            record = self.records[record_id]
            encoded: list[dict[str, str]] = []
            for link in self._links.get(record_id, []):
                if link.target_id is None:
                    encoded.append(link.raw)
                    continue
                target = self.records.get(link.target_id)
                if target is None:
                    continue
                same_place = (slugify(target.workspace or "") == slugify(record.workspace or "")
                              and slugify(target.project or "") == slugify(record.project or ""))
                ref = target.key if (target.key and same_place) else target.id
                encoded.append({"type": link.type, "target": ref})
            if encoded != list(record.relations or []):
                self.records[record_id] = dataclasses.replace(record, relations=encoded)

    # ------------------------------------------------------------------ metadados

    def set_meta(self, rel: str, data: dict[str, Any] | None) -> None:
        if data is None:
            self.metas.pop(rel, None)
        else:
            self.metas[rel] = data
        self._invalidate()

    def meta(self, rel: str) -> dict[str, Any]:
        return dict(self.metas.get(rel) or {})

    # ------------------------------------------------------------------ resultado

    def files(self) -> dict[str, str | None]:
        """{path relativo: conteúdo novo, ou None para remover} do que mudou."""
        self._encode_links()
        out: dict[str, str | None] = {}
        for rel in set(self._base.metas) | set(self.metas):
            new = self.metas.get(rel)
            if new == self._base.metas.get(rel):
                continue
            out[rel] = dump_meta(new) if new is not None else None
        base = self._base.records
        for record_id, old in base.items():
            if record_id not in self.records:
                out[old.path] = None
        occupied = {
            r.path: r.id for r in self.records.values()
            if base.get(r.id) is r and r.path
        }
        written: dict[str, str] = {}
        for record_id, record in self.records.items():
            old = base.get(record_id)
            if old is record:
                continue
            path, text = record_text(record)
            other = occupied.get(path)
            if path in written or (other is not None and other != record_id):
                raise ValidationError(
                    f"Dois itens no mesmo arquivo ({path}): key repetida no project?"
                )
            written[path] = text
            if old is not None and old.path and old.path != path:
                out.setdefault(old.path, None)
        out.update(written)
        return out


# --------------------------------------------------------------------------- conexão


class Brain:
    """Leitura e escrita do segundo cérebro de uma conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None,
                 conn: ConnectionConfig | None = None) -> None:
        self.conn = conn or resolve_connection(connection_id)
        self.cid = self.conn.id
        self.root = self.conn.clone_path()
        self.lock = lock_for(self.cid)
        self._usage: dict[str, dict[str, Any]] | None = None
        self.refresh()

    def refresh(self) -> Snapshot:
        with self.lock:
            store = store_for(self.conn)
            self.snapshot = Snapshot(
                {r.id: r for r in store.items()}, read_metas(self.root)
            )
            self.store = store
        return self.snapshot

    # ------------------------------------------------------------------ escrita

    @contextmanager
    def editing(self) -> Iterator[Draft]:
        """Trava a conexão (nesta thread e entre processos), relê a pasta e entrega um
        rascunho; quem chama faz o `commit` dentro do bloco."""
        held: set[str] = getattr(_editing, "held", None) or set()
        _editing.held = held
        with self.lock:
            if self.cid in held:
                self.refresh()
                yield Draft(self.snapshot)
                return
            with folder_lock(self.root):
                held.add(self.cid)
                try:
                    self.refresh()
                    yield Draft(self.snapshot)
                finally:
                    held.discard(self.cid)

    def commit(self, draft: Draft, message: str) -> PublishResult | None:
        """Publica o rascunho numa publicação só (None se nada mudou) e relê a pasta."""
        files = draft.files()
        if not files:
            return None
        with self.lock:
            result = git_for(self.conn).publish(files, message)
            self.refresh()
        return result

    # ------------------------------------------------------------------ itens

    def usage(self) -> dict[str, dict[str, Any]]:
        if self._usage is None:
            self._usage = local_state.get_usage(self.cid)
        return self._usage

    def secret_path(self, item_id: str) -> Path:
        """`.secrets/<id>.enc`; id fora de [A-Za-z0-9-] ou destino fora da pasta: erro."""
        problem = id_problem(item_id)
        if problem:
            raise ValidationError(problem)
        return safe_join(self.root, f"{SECRETS_DIRNAME}/{item_id}.enc")

    def view(self, record: ItemRecord) -> Item:
        use = self.usage().get(record.id) or {}
        last = use.get("last_used")
        try:
            last_dt = datetime.fromisoformat(last.rstrip("Z")) if last else None
        except (TypeError, ValueError):
            last_dt = None
        return Item(
            id=record.id, key=record.key,
            workspace_id=slugify(record.workspace or ""), project_id=slugify(record.project or ""),
            subject_id=slugify(record.subject) if record.subject else None,
            workspace=record.workspace or "", project=record.project or "",
            subject=record.subject, type=record.type, title=record.title,
            summary=record.summary, content=record.content, status=record.status or "active",
            memory_class=record.memory_class, tags=sorted(record.tags or []),
            labels=sorted(record.labels or []), scope_paths=list(record.scope_paths or []),
            confidence=record.confidence, importance=record.importance,
            ttl_days=record.ttl_days, keywords=record.keywords, source=record.source,
            created_at=record.created_at, updated_at=record.updated_at,
            expires_at=expires_at(record), path=record.path,
            access_count=int(use.get("uses") or 0), last_accessed=last_dt,
            has_value=record.type == "secret" and self.secret_path(record.id).is_file(),
        )

    def views(self, records: Iterable[ItemRecord]) -> list[Item]:
        return [self.view(r) for r in records]

    def track(self, ids: Iterable[str]) -> None:
        """Conta um uso de cada item (contador local; nunca derruba a operação)."""
        local_state.track(self.cid, ids)
        self._usage = None
