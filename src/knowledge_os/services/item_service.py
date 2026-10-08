"""Item service: CRUD, upsert por chave, lote e busca — tudo nos arquivos da conexão.

Toda escrita monta um rascunho (`brain.Draft`) e publica de uma vez pelo repositório git da
conexão: em `review_mode="direct"` grava, comita (e empurra, se houver remote) e a leitura
seguinte já vê o resultado; em `review_mode="pr"` abre PR (ou Issue) e a pasta continua na
branch principal — a mudança só aparece depois do merge e de um sync.
"""

import dataclasses
import logging
import re
import uuid
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.schemas.item_schemas import MEMORY_CLASSES, ItemCreate, ItemUpdate
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
from knowledge_os.services.git_repo_service import PublishResult
from knowledge_os.services.item_file import slugify
from knowledge_os.services.secret_guard import ensure_no_secrets
from knowledge_os.storage.files import ItemRecord
from knowledge_os.storage.search import search as search_records

logger = logging.getLogger(__name__)

# Campos que trariam o valor de um segredo pelo agente: recusados no item_save.
VALUE_FIELDS = frozenset({"value", "valor", "secret_value", "secret", "token", "password",
                          "senha", "api_key", "apikey"})
# Palavra com cara de credencial aleatória (16+ caracteres, maiúscula, minúscula e dígito).
_RANDOM_WORD = re.compile(r"\S{16,}")


def _looks_random(text: str | None) -> bool:
    for word in _RANDOM_WORD.findall(text or ""):
        if (any(c.islower() for c in word) and any(c.isupper() for c in word)
                and any(c.isdigit() for c in word)):
            return True
    return False


UPDATABLE_FIELDS = (
    "title", "type", "summary", "content", "confidence", "importance", "ttl_days",
    "keywords", "source", "status", "scope_paths", "tags", "labels",
)
_NON_NULLABLE = ("title", "type", "summary", "content")
_TEXT_FIELDS = ("title", "summary", "content", "keywords")
_RANK = {m: i for i, m in enumerate(MEMORY_CLASSES)}


def _validation_message(exc: PydanticValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
        for e in exc.errors()
    )


def _names(values: list[str] | None) -> list[str]:
    """Tags/labels sem repetição e sem vazio, em ordem alfabética (arquivo estável)."""
    return sorted({v.strip() for v in values or [] if v and v.strip()})


def _ids(value: str | list[str] | None) -> set[str] | None:
    if not value:
        return None
    return {value} if isinstance(value, str) else set(value)


def review_result(index: int, publish: PublishResult) -> dict[str, Any]:
    if publish.status == "pending_review":
        return {"index": index, "status": "pending_review", "pr_url": publish.pr_url}
    return {"index": index, "status": "issue_opened", "issue_url": publish.issue_url}


def run_search(
    brain: Brain,
    workspace_id: str | None,
    project_id: str | list[str] | None,
    query: str,
    subject_id: str | list[str] | None = None,
    types: list[str] | None = None,
    memory_classes: list[str] | None = None,
    limit: int = 10,
    include_inactive: bool = False,
    tags: list[str] | None = None,
    labels: list[str] | None = None,
) -> list[tuple[ItemRecord, float]]:
    """Busca nos itens da conexão já lidos por `brain` (pares item, score)."""
    if limit < 1:
        raise ValidationError("limit deve ser >= 1")
    projects, subjects = _ids(project_id), _ids(subject_id)
    type_set, class_set = set(types or []), set(memory_classes or [])
    want_tags, want_labels = set(_names(tags)), set(_names(labels))
    now = utcnow()

    def wanted(r: ItemRecord) -> bool:
        if workspace_id and slugify(r.workspace or "") != workspace_id:
            return False
        if projects is not None and slugify(r.project or "") not in projects:
            return False
        if subjects is not None and (not r.subject or slugify(r.subject) not in subjects):
            return False
        if type_set and r.type not in type_set:
            return False
        if class_set and r.memory_class not in class_set:
            return False
        if want_tags and not want_tags <= set(r.tags or []):
            return False
        if want_labels and not want_labels <= set(r.labels or []):
            return False
        if not include_inactive:
            if (r.status or "active") not in ("active", "done") or is_expired(r, now):
                return False
        return True

    usage = brain.usage()

    def tie(r: ItemRecord) -> tuple[Any, ...]:
        uses = int((usage.get(r.id) or {}).get("uses") or 0)
        return (r.importance or 0, r.confidence or 0, uses, r.updated_at)

    records = [r for r in brain.snapshot.records.values() if wanted(r)]
    return search_records(records, (query or "").strip(), limit, key=tie,
                          index=brain.store.index)


class ItemService:
    """Operações de CRUD e busca sobre os itens da conexão (a informada ou a padrão)."""

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

    # ------------------------------------------------------------------ validação

    @staticmethod
    def _validate_create(**kwargs: Any) -> ItemCreate:
        try:
            data = ItemCreate(**kwargs)
        except PydanticValidationError as exc:
            raise ValidationError(_validation_message(exc)) from exc
        ensure_no_secrets(**{f: getattr(data, f) for f in _TEXT_FIELDS})
        return data

    @staticmethod
    def _check_update(fields: dict[str, Any]) -> None:
        unknown = sorted(set(fields) - set(UPDATABLE_FIELDS))
        if unknown:
            raise ValidationError(f"Campos não atualizáveis: {', '.join(unknown)}")
        for name in _NON_NULLABLE:
            if name in fields and fields[name] is None:
                raise ValidationError(f"{name} não pode ser nulo")
        try:
            ItemUpdate(**fields)
        except PydanticValidationError as exc:
            raise ValidationError(_validation_message(exc)) from exc
        ensure_no_secrets(**{f: fields.get(f) for f in _TEXT_FIELDS})

    # ------------------------------------------------------------------ rascunho

    @staticmethod
    def _insert(
        d: Draft, ws_name: str, pj_name: str, subject: str | None, data: ItemCreate
    ) -> ItemRecord:
        if data.key and d.by_key(slugify(ws_name), slugify(pj_name), data.key) is not None:
            raise ValidationError(f"Já existe item com key {data.key!r} neste project (use upsert)")
        now = utcnow()
        record = ItemRecord(
            id=str(uuid.uuid4()), key=data.key, workspace=ws_name, project=pj_name,
            subject=subject, type=data.type, title=data.title, status=data.status,
            memory_class=data.memory_class, tags=_names(data.tags), labels=_names(data.labels),
            scope_paths=list(data.scope_paths or []), confidence=data.confidence,
            importance=data.importance,
            ttl_days=data.ttl_days if data.memory_class == "ephemeral" else None,
            keywords=data.keywords, source=data.source, created_at=now, updated_at=now,
            relations=[], summary=data.summary, content=data.content,
        )
        return d.put(record)

    @staticmethod
    def _apply(brain: Brain, record: ItemRecord, fields: dict[str, Any]) -> tuple[ItemRecord, bool]:
        """Aplica campos ao item. (item novo, mudou?)."""
        new_type = fields.get("type", record.type)
        if (record.type == "secret" and new_type != "secret"
                and brain.secret_path(record.id).is_file()):
            raise ValidationError(
                "Este segredo tem valor. Apague o valor (na UI) antes de mudar o tipo do item."
            )
        if record.memory_class == "ephemeral" and fields.get("ttl_days", record.ttl_days) is None:
            raise ValidationError("ttl_days é obrigatório para memory_class 'ephemeral'")
        changes: dict[str, Any] = {}
        for name, value in fields.items():
            if name in ("tags", "labels"):
                value = _names(value)
                if sorted(getattr(record, name) or []) != value:
                    changes[name] = value
            elif name == "scope_paths":
                value = list(value or [])
                if list(record.scope_paths or []) != value:
                    changes[name] = value
            elif name == "ttl_days" and record.memory_class == "ephemeral":
                changes[name] = value  # renovar conta a partir de agora, mesmo com o mesmo prazo
            elif getattr(record, name) != value:
                changes[name] = value
        if not changes:
            return record, False
        return dataclasses.replace(record, **changes), True

    @staticmethod
    def _raise_class(record: ItemRecord, target: str) -> tuple[ItemRecord, bool]:
        """Sobe a classe de memória se `target` for maior; nunca rebaixa."""
        if target not in _RANK:
            raise ValidationError(f"memory_class inválido: {target!r}")
        if _RANK[target] <= _RANK.get(record.memory_class, 0):
            return record, False
        changes: dict[str, Any] = {"memory_class": target}
        if target != "ephemeral":
            changes["ttl_days"] = None
        return dataclasses.replace(record, **changes), True

    def _upsert_in(
        self, brain: Brain, d: Draft, ws_name: str, pj_name: str, subject: str | None,
        key: str, fields: dict[str, Any],
    ) -> tuple[ItemRecord, str]:
        fields = {k: v for k, v in fields.items() if v is not None}
        existing = d.by_key(slugify(ws_name), slugify(pj_name), key)
        if existing is None:
            data = self._validate_create(
                workspace_id=slugify(ws_name), project_id=slugify(pj_name), key=key,
                **{"tags": [], "labels": [], "scope_paths": [], **fields},
            )
            return self._insert(d, ws_name, pj_name, subject, data), "created"
        memory_class = fields.pop("memory_class", None)
        self._check_update(fields)
        record, changed = self._apply(brain, existing, fields)
        if memory_class:
            record, raised = self._raise_class(record, memory_class)
            changed = changed or raised
        if subject is not None and record.subject != subject:
            record, changed = dataclasses.replace(record, subject=subject), True
        if not changed:
            return existing, "unchanged"
        return d.put(dataclasses.replace(record, updated_at=utcnow())), "updated"

    @staticmethod
    def _relate(d: Draft, source_id: str, rel: dict[str, Any]) -> bool:
        """Cria a relação item → alvo (id ou key do mesmo project). False se já existia."""
        from knowledge_os.services.relation_service import RELATION_TYPES

        rtype, target_ref = rel.get("type"), rel.get("target")
        if rtype not in RELATION_TYPES:
            raise ValidationError(f"type inválido: {rtype!r}. Válidos: {', '.join(RELATION_TYPES)}")
        if not target_ref:
            raise ValidationError("relação sem target")
        source = d.require(source_id)
        target = d.resolve_target(source, str(target_ref))
        if target is None:
            raise NotFoundError(f"Alvo não encontrado: {target_ref}")
        if target.id == source_id:
            raise ValidationError("Um item não pode se relacionar consigo mesmo")
        if not d.add_link(source_id, rtype, target.id):
            return False
        if rtype == "supersedes" and target.status != "superseded":
            d.update(target.id, status="superseded", updated_at=utcnow())
        return True

    def _publish(self, brain: Brain, d: Draft, message: str) -> PublishResult | None:
        return brain.commit(d, message)

    # ------------------------------------------------------------------ CRUD

    def create(
        self,
        workspace_id: str,
        project_id: str,
        type: str,
        memory_class: str,
        title: str,
        summary: str,
        content: str,
        subject_id: str | None = None,
        tags: list[str] | None = None,
        labels: list[str] | None = None,
        confidence: int | None = None,
        importance: int | None = None,
        ttl_days: int | None = None,
        key: str | None = None,
        keywords: str | None = None,
        source: str | None = None,
        status: str = "active",
        scope_paths: list[str] | None = None,
    ) -> Item:
        """Cria um item no workspace/project (que precisam existir)."""
        data = self._validate_create(
            workspace_id=workspace_id, project_id=project_id, subject_id=subject_id, type=type,
            memory_class=memory_class, title=title, summary=summary, content=content,
            tags=tags or [], labels=labels or [], confidence=confidence,
            importance=importance, ttl_days=ttl_days, key=key, keywords=keywords,
            source=source, status=status, scope_paths=scope_paths or [],
        )
        brain = self.brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            subject = d.subject(ws.id, pj.id, subject_id).name if subject_id else None
            record = self._insert(d, ws.name, pj.name, subject, data)
            self._publish(brain, d, f"knowledge-os: cria {record.title}")
        logger.info("Item criado: %s", record.id)
        return self._get(brain, record.id)

    def update(self, item_id: str, **fields: Any) -> Item:
        """Atualiza só os campos informados (tags e labels substituem as atuais)."""
        self._check_update(fields)
        brain = self.brain()
        with brain.editing() as d:
            record, changed = self._apply(brain, d.require(item_id), fields)
            if changed:
                d.put(dataclasses.replace(record, updated_at=utcnow()))
                self._publish(brain, d, f"knowledge-os: atualiza {record.title}")
        return self._get(brain, item_id)

    def upsert(
        self, workspace_id: str, project_id: str, key: str, **fields: Any
    ) -> tuple[Item, str]:
        """Cria ou atualiza o item de `key` no project. Retorna (item, created|updated|unchanged).

        `memory_class` só sobe (nunca rebaixa um item existente). Na criação, os campos
        obrigatórios de item_create valem.
        """
        brain = self.brain()
        with brain.editing() as d:
            ws_name, pj_name = location_names(d, workspace_id, project_id)
            record, action = self._upsert_in(brain, d, ws_name, pj_name, None, key, fields)
            self._publish(brain, d, f"knowledge-os: salva {key}")
        return self._get(brain, record.id), action

    def batch_upsert(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Upsert de vários itens numa publicação. Cada entrada traz workspace, project e key."""
        for i, e in enumerate(entries):
            missing = [f for f in ("workspace", "project", "key") if not e.get(f)]
            if missing:
                raise ValidationError(f"Entrada {i}: faltam {', '.join(missing)}")
        return [{k: r[k] for k in ("key", "id", "action")} for r in self.save(entries)]

    @staticmethod
    def _prepare(i: int, raw: dict[str, Any]) -> dict[str, Any]:
        e = dict(raw)
        if VALUE_FIELDS & {str(k).lower() for k in e}:
            raise ValidationError(
                f"Entrada {i}: o valor de um segredo não passa pelo agente. Grave o item "
                "(type secret) sem valor e passe ao usuário o fill_url da resposta: ele "
                "preenche na UI local."
            )
        if e.get("type") == "secret" and not e.get("key") and not e.get("id"):
            raise ValidationError(
                f"Entrada {i}: segredo precisa de key (segredo/<nome>): é por ela que o "
                "knowledge-mcp run o encontra."
            )
        if e.get("type") == "secret":
            if e.get("content") and e.get("content") != e.get("summary"):
                raise ValidationError(
                    f"Entrada {i}: segredo não tem corpo — só title e summary (para que "
                    "serve). O valor vai pela UI (fill_url)."
                )
            if any(_looks_random(e.get(f)) for f in ("title", "summary", "keywords")):
                raise ValidationError(
                    f"Entrada {i}: o texto do segredo parece conter a credencial. Descreva "
                    "só para que serve; o valor vai pela UI (fill_url)."
                )
            if e.get("summary"):
                e["content"] = e["summary"]  # o resumo diz para que serve
        return e

    def save(
        self, entries: list[dict[str, Any]], default_location: tuple[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Grava vários itens numa publicação só; cada entrada escolhe o modo pelo que traz.

        - `id`: atualiza esse item (só os campos informados).
        - `key`: upsert no project (cria ou atualiza; não duplica).
        - nenhum dos dois: cria e devolve `similar` com títulos parecidos já existentes.

        Em qualquer modo: `memory_class` só sobe (promoção), `ttl_days` renova um ephemeral a
        partir de agora, e `relations: [{type, target}]` liga ao alvo (id, ou key do mesmo
        project, inclusive itens criados no mesmo lote); `supersedes` marca o alvo como
        substituído. Workspace/project vêm da entrada ou de `default_location` (nomes ou ids) e
        passam a existir com o item. `subject` (nome do assunto) vale dentro do project. Com
        `id`: se a entrada também trouxer `workspace`+`project`, o item é *movido* para lá — o
        `subject`, se vier, vale no project novo; se não vier, o item fica sem subject. Só
        `subject` (sem workspace/project) move o item para esse subject no project atual. Em
        todos os casos de `id`, id, created_at, tags, labels e relations não mudam — só a
        localização. Qualquer erro desfaz o lote inteiro e aponta a entrada.
        """
        if not entries:
            return []
        prepared = [self._prepare(i, raw) for i, raw in enumerate(entries)]
        brain = self.brain()
        results: list[dict[str, Any]] = []
        touched: list[int] = []
        with brain.editing() as d:
            links: list[tuple[int, str, dict[str, Any]]] = []
            for i, e in enumerate(prepared):
                relations = e.pop("relations", None) or []
                item_id, key = e.pop("id", None), e.pop("key", None)
                ws, dm = e.pop("workspace", None), e.pop("project", None)
                sj = e.pop("subject", None)
                fields = {k: v for k, v in e.items() if v is not None}
                label = key or item_id or fields.get("title", "?")
                similar: list[dict[str, Any]] = []
                try:
                    if item_id:
                        record, action = self._save_by_id(brain, d, item_id, ws, dm, sj, fields)
                    else:
                        if ws and dm:
                            ws_name, pj_name = location_names(d, ws, dm)
                        elif default_location:
                            ws_name, pj_name = location_names(d, *default_location)
                        else:
                            raise ValidationError(
                                f"Entrada {i}: informe workspace e project (ou repo)"
                            )
                        subject = subject_name(d, ws_name, pj_name, sj) if sj else None
                        if key:
                            record, action = self._upsert_in(
                                brain, d, ws_name, pj_name, subject, key, fields
                            )
                        else:
                            if fields.get("title"):
                                similar = similar_in(d, slugify(ws_name), fields["title"])
                            data = self._validate_create(
                                workspace_id=slugify(ws_name), project_id=slugify(pj_name),
                                **{"tags": [], "labels": [], "scope_paths": [], **fields},
                            )
                            record = self._insert(d, ws_name, pj_name, subject, data)
                            action = "created"
                except (ValidationError, NotFoundError) as exc:
                    if str(exc).startswith(f"Entrada {i}"):
                        raise
                    raise ValidationError(f"Entrada {i} ({label}): {exc}") from exc
                row: dict[str, Any] = {"index": i, "id": record.id, "key": record.key,
                                       "action": action}
                if similar:
                    row["similar"] = similar
                results.append(row)
                touched.append(i)
                links += [(i, record.id, r) for r in relations]
            for i, record_id, rel in links:
                try:
                    created = self._relate(d, record_id, rel)
                except (ValidationError, NotFoundError) as exc:
                    raise ValidationError(f"Entrada {i}, relação {rel}: {exc}") from exc
                if created:
                    results[i]["relations"] = results[i].get("relations", 0) + 1
            publish = self._publish(brain, d, f"knowledge-os: salva {len(entries)} item(ns)")
        if publish is not None and publish.status != "published":
            return [review_result(i, publish) for i in touched]
        return results

    def _save_by_id(
        self, brain: Brain, d: Draft, item_id: str, ws: str | None, dm: str | None,
        sj: str | None, fields: dict[str, Any],
    ) -> tuple[ItemRecord, str]:
        record = d.require(item_id)
        moved = False
        if ws and dm:
            ws_name, pj_name = location_names(d, ws, dm)
            subject = subject_name(d, ws_name, pj_name, sj) if sj else None
            record = dataclasses.replace(record, workspace=ws_name, project=pj_name,
                                         subject=subject)
            moved = True
        elif sj:
            subject = subject_name(d, record.workspace or "", record.project or "", sj)
            record = dataclasses.replace(record, subject=subject)
            moved = True
        memory_class = fields.pop("memory_class", None)
        self._check_update(fields)
        record, changed = self._apply(brain, record, fields)
        if memory_class:
            record, raised = self._raise_class(record, memory_class)
            changed = changed or raised
        if not (changed or moved):
            return record, "unchanged"
        if record.key and moved:
            clash = d.by_key(slugify(record.workspace or ""), slugify(record.project or ""),
                             record.key)
            if clash is not None and clash.id != record.id:
                raise ValidationError(
                    f"Já existe item com key {record.key!r} no project de destino"
                )
        return d.put(dataclasses.replace(record, updated_at=utcnow())), "updated"

    def delete(self, item_id: str) -> bool:
        """Remove o item (e o valor, se for segredo). NotFoundError se não existir."""
        result = self.delete_published(item_id)
        return result["status"] == "deleted"

    def delete_published(self, item_id: str) -> dict[str, Any]:
        """Remove o arquivo do item e publica a remoção.

        Modo `direct`: sai da pasta na hora. Modo `pr`: abre PR (ou Issue) de remoção e o item
        continua na pasta até o PR ser mergeado e sincronizado.
        """
        brain = self.brain()
        with brain.editing() as d:
            record = d.require(item_id)
            d.remove(item_id)
            publish = self._publish(brain, d, f"knowledge-os: remove {record.path}")
        if publish is not None and publish.status != "published":
            out = review_result(0, publish)
            out.pop("index")
            return {**out, "id": item_id}
        brain.secret_path(item_id).unlink(missing_ok=True)
        logger.info("Item removido: %s", item_id)
        return {"status": "deleted", "id": item_id}

    @staticmethod
    def _get(brain: Brain, item_id: str) -> Item:
        return brain.view(brain.snapshot.require(item_id))

    def get(self, item_id: str) -> Item:
        """Retorna o item completo (com content, tags e labels)."""
        return self._get(self.brain(), item_id)

    def get_by_key(self, workspace_id: str, project_id: str, key: str) -> Item:
        """Item de `key` no workspace/project. Levanta NotFoundError."""
        brain = self.brain()
        record = brain.snapshot.by_key(workspace_id, project_id, key)
        if record is None:
            raise NotFoundError(f"Item não encontrado: key {key!r}")
        return brain.view(record)

    # ------------------------------------------------------------------ busca

    def search(
        self,
        workspace_id: str | None,
        project_id: str | list[str] | None,
        query: str,
        subject_id: str | list[str] | None = None,
        types: list[str] | None = None,
        memory_classes: list[str] | None = None,
        limit: int = 10,
        include_inactive: bool = False,
        track: bool = True,
        tags: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Busca em title+summary+keywords+content. Nunca inclui content.

        Com consulta, ordena por relevância (BM25 com peso maior para o título) e desempata
        por importance, confidence, usos e updated_at; sem consulta, lista por esses critérios.
        Sem workspace, busca em todos os da conexão. Omite itens substituídos, obsoletos e
        ephemeral vencidos, salvo `include_inactive`. A consulta é normalizada para PT-BR (sem
        acento, radical, prefixo); se exigir todos os termos não acha nada, tenta qualquer termo.
        Com `track`, conta um uso de cada item devolvido.

        `tags` e `labels` filtram por conjunção: o item precisa ter **todas** as informadas.
        São filtros, não termos de busca — o que faz o item ser encontrado por texto é
        `keywords`.
        """
        brain = self.brain()
        hits = run_search(
            brain, workspace_id, project_id, query, subject_id, types, memory_classes, limit,
            include_inactive, tags, labels,
        )
        usage = brain.usage()
        results = [
            {
                "id": r.id, "key": r.key, "type": r.type, "memory_class": r.memory_class,
                "project": r.project, "subject": r.subject, "title": r.title,
                "summary": r.summary, "score": float(score),
                "uses": int((usage.get(r.id) or {}).get("uses") or 0),
                "tags": sorted(r.tags or []), "labels": sorted(r.labels or []),
                "workspace_id": slugify(r.workspace or ""), "project_id": slugify(r.project or ""),
            }
            for r, score in hits
        ]
        if results and track:
            brain.track(r["id"] for r in results)
        return results

    def track_use(self, ids: list[str]) -> None:
        """Conta o uso (item entregue a um agente); falha aqui nunca derruba a leitura."""
        if not ids:
            return
        try:
            self.brain().track(ids)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Contagem de uso ignorada: %s", exc)

    def similar(self, workspace_id: str, title: str, limit: int = 3) -> list[dict[str, Any]]:
        """Itens ativos do workspace com título parecido (para avisar antes de duplicar)."""
        return similar_in(self.brain().snapshot, workspace_id, title, limit)


# --------------------------------------------------------------------------- helpers


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


def similar_in(
    snap: Snapshot, workspace_id: str, title: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Itens ativos do workspace com título parecido, num `Snapshot` qualquer."""
    now = utcnow()
    records = [
        r for r in snap.items_in(workspace_id)
        if (r.status or "active") in ("active", "done") and not is_expired(r, now)
    ]
    hits = search_records(records, title, limit,
                          key=lambda r: (r.importance or 0, r.confidence or 0, r.updated_at))
    return [{"id": r.id, "key": r.key, "title": r.title, "summary": r.summary} for r, _ in hits]
