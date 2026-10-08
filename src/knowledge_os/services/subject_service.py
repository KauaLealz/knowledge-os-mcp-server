"""Subject service: o agrupador opcional de itens dentro de um project.

O subject de um item é o campo `subject` do frontmatter; a lista `subjects` do
`.knowledge.yaml` do project guarda os subjects sem item e os que têm descrição ou `scope`
explícito (`[{name, description?, scope?}]`; um nome solto também vale). Ao mesclar, vale o
scope do destino para o subject; ao mesclar ou remover, o item que herdava e mudaria de
alcance ganha o scope de antes como explícito (`Draft.keep_scopes`: ninguém muda de alcance
sem pedir). `scope` segue a convenção de `workspace_service` (None / valor / `""`).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.brain import (
    Brain,
    Draft,
    Project,
    Subject,
    Workspace,
    check_name,
    meta_location,
    utcnow,
)
from knowledge_os.services.item_file import slugify
from knowledge_os.services.workspace_service import apply_meta, check_scope, effective

logger = logging.getLogger(__name__)


def _entry_id(entry: Any) -> str:
    return slugify(entry if isinstance(entry, str) else str(entry.get("name") or ""))


def _entry(name: str, description: str | None, scope: str | None) -> Any:
    """Entrada da lista `subjects`: só o nome, se não há descrição nem scope."""
    data = apply_meta({"name": name}, description or None, scope or None)
    return data if len(data) > 1 else name


def _set_subject_meta(
    d: Draft, ws: Workspace, pj: Project, old_id: str | None, new: Any | None
) -> None:
    """Troca (ou tira, com `new=None`) a entrada `old_id` da lista do `.knowledge.yaml`."""
    rel = meta_location(ws.id, pj.id)
    data = d.meta(rel)
    entries = [e for e in data.get("subjects") or [] if _entry_id(e) != old_id]
    if new is not None and all(_entry_id(e) != _entry_id(new) for e in entries):
        entries.append(new)
    if entries == list(data.get("subjects") or []):
        return
    data = {"name": pj.name, **data}
    if entries:
        data["subjects"] = entries
    else:
        data.pop("subjects", None)
    d.set_meta(rel, data)


class SubjectService:
    """Operações sobre os subjects de um project da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def _brain(self) -> Brain:
        return Brain(self._connection_id)

    def create(self, workspace_id: str, project_id: str, name: str,
               description: str | None = None, scope: str | None = None) -> Subject:
        """Cria um subject. NotFoundError se o project não existe; ValidationError se duplicado
        ou se o scope não é um de `SCOPES`."""
        scope = check_scope(scope or None)
        name = check_name(name, "subject")
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            if d.find_subject(ws.id, pj.id, slugify(name)) is not None:
                raise ValidationError(f"Subject já existe no project: {name}")
            _set_subject_meta(d, ws, pj, None, _entry(name, description, scope))
            brain.commit(d, f"knowledge-os: cria subject {pj.name}/{name}")
        logger.info("Subject criado: %s (project %s)", name, project_id)
        return brain.snapshot.subject(ws.id, pj.id, slugify(name))

    def list(self, workspace_id: str, project_id: str) -> list[Subject]:
        """Subjects do project, por nome."""
        return self._brain().snapshot.subjects(workspace_id, project_id)

    def rows(self, workspace: str, project: str) -> list[dict[str, Any]]:
        """Para `subject_list`/API: `[{id, name, description, scope, scope_explicit, items}]`
        por nome (`scope` = o que vale, com a herança do project e do workspace)."""
        snap = self._brain().snapshot
        ws = snap.workspace(workspace)
        pj = snap.project(ws.id, project)
        counts: dict[str, int] = {}
        for record in snap.items_in(ws.id, pj.id):
            if record.subject:
                counts[slugify(record.subject)] = counts.get(slugify(record.subject), 0) + 1
        return [{"id": sj.id, "name": sj.name, "description": sj.description,
                 "scope": effective(sj.scope, pj.scope, ws.scope), "scope_explicit": sj.scope,
                 "items": counts.get(sj.id, 0)}
                for sj in snap.subjects(ws.id, pj.id)]

    def get(self, workspace_id: str, project_id: str, name: str) -> Subject:
        """Subject por nome ou id. NotFoundError se não existe."""
        return self._brain().snapshot.subject(workspace_id, project_id, name)

    def count_items(self, workspace_id: str, project_id: str) -> dict[str, int]:
        """Itens por subject (id) no project."""
        snap = self._brain().snapshot
        pj = snap.project(workspace_id, project_id)
        counts: dict[str, int] = {}
        for record in snap.items_in(pj.workspace_id, pj.id):
            if record.subject:
                key = slugify(record.subject)
                counts[key] = counts.get(key, 0) + 1
        return counts

    def update(self, workspace_id: str, project_id: str, ref: str,
               new_name: str | None = None, description: str | None = None,
               scope: str | None = None) -> Subject:
        """Troca o nome (regravando os itens), a descrição e/ou o scope; o que vier None fica
        como está (`scope=""` volta a herdar). ValidationError se new_name já existe."""
        scope = check_scope(scope, clearable=True)
        name_given = check_name(new_name, "subject") if new_name is not None else None
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            sj = d.subject(ws.id, pj.id, ref)
            name = name_given or sj.name
            new_id = slugify(name)
            if new_id != sj.id and d.find_subject(ws.id, pj.id, new_id) is not None:
                raise ValidationError(f"Subject já existe no project: {name}")
            if name != sj.name:
                for record in d.items_in(ws.id, pj.id, sj.id):
                    d.put(dataclasses.replace(record, subject=name, updated_at=utcnow()))
            listed = d.meta(meta_location(ws.id, pj.id)).get("subjects") or []
            in_meta = any(_entry_id(e) == sj.id for e in listed)
            new_desc = sj.description if description is None else description
            new_scope = sj.scope if scope is None else scope
            entry = _entry(name, new_desc, new_scope)
            if in_meta or not isinstance(entry, str):
                _set_subject_meta(d, ws, pj, sj.id, entry)
            brain.commit(d, f"knowledge-os: atualiza subject {pj.name}/{name}")
        logger.info("Subject atualizado: %s -> %s (project %s)", ref, name, project_id)
        return brain.snapshot.subject(ws.id, pj.id, new_id)

    def merge(self, workspace_id: str, project_id: str, source: str,
              target: str) -> dict[str, Any]:
        """Move os itens de source para target e apaga source."""
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            src = d.subject(ws.id, pj.id, source)
            tgt = d.subject(ws.id, pj.id, target)
            if src.id == tgt.id:
                raise ValidationError("source e target são o mesmo subject")
            records = d.items_in(ws.id, pj.id, src.id)
            for record in records:
                d.put(dataclasses.replace(record, subject=tgt.name, updated_at=utcnow()))
            _set_subject_meta(d, ws, pj, src.id, None)
            changes = d.keep_scopes()
            brain.commit(d, f"knowledge-os: mescla subject {src.name} em {tgt.name}")
        logger.info("Subject mesclado: %s -> %s (project %s)", source, target, project_id)
        return {"merged_items": len(records), "scope_changes": {"items": changes}}

    @staticmethod
    def _delete_in(d: Draft, ws: Workspace, pj: Project, sj: Subject) -> int:
        """Tira o subject dos itens e do `.knowledge.yaml`; quem herdava o scope dele ganha o
        scope de antes como explícito (`Draft.keep_scopes`). Devolve quantos ganharam."""
        for record in d.items_in(ws.id, pj.id, sj.id):
            d.put(dataclasses.replace(record, subject=None, updated_at=utcnow()))
        _set_subject_meta(d, ws, pj, sj.id, None)
        return d.keep_scopes()

    def delete_scope_changes(self, workspace_id: str, project_id: str, name: str) -> int:
        """Prévia do `delete`: quantos itens ganhariam scope explícito (nada é gravado)."""
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            sj = d.find_subject(ws.id, pj.id, name)
            return 0 if sj is None else self._delete_in(d, ws, pj, sj)

    def delete(self, workspace_id: str, project_id: str, name: str) -> bool:
        """Remove o subject, deixando os itens dele sem subject (com o alcance de antes, ver
        `_delete_in`), num commit. False se não existe."""
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            sj = d.find_subject(ws.id, pj.id, name)
            if sj is None:
                logger.debug("Subject inexistente para delete: %s", name)
                return False
            self._delete_in(d, ws, pj, sj)
            brain.commit(d, f"knowledge-os: remove subject {pj.name}/{sj.name}")
        logger.info("Subject removido: %s", name)
        return True
