"""Subject service: o agrupador opcional de itens dentro de um project.

O subject de um item é o campo `subject` do frontmatter; os subjects sem item ficam na lista
`subjects` do `.knowledge.yaml` do project.
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

logger = logging.getLogger(__name__)


def _entry_id(entry: Any) -> str:
    return slugify(entry if isinstance(entry, str) else str(entry.get("name") or ""))


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

    def create(
        self, workspace_id: str, project_id: str, name: str, description: str | None = None
    ) -> Subject:
        """Cria um subject. NotFoundError se o project não existe; ValidationError se duplicado."""
        name = check_name(name, "subject")
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            if d.find_subject(ws.id, pj.id, slugify(name)) is not None:
                raise ValidationError(f"Subject já existe no project: {name}")
            entry: Any = {"name": name, "description": description} if description else name
            _set_subject_meta(d, ws, pj, None, entry)
            brain.commit(d, f"knowledge-os: cria subject {pj.name}/{name}")
        logger.info("Subject criado: %s (project %s)", name, project_id)
        return brain.snapshot.subject(ws.id, pj.id, slugify(name))

    def list(self, workspace_id: str, project_id: str) -> list[Subject]:
        """Subjects do project, por nome."""
        return self._brain().snapshot.subjects(workspace_id, project_id)

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

    def rename(self, workspace_id: str, project_id: str, name: str, new_name: str) -> Subject:
        """Renomeia um subject dentro do project. ValidationError se new_name já existe."""
        new_name = check_name(new_name, "subject")
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            sj = d.subject(ws.id, pj.id, name)
            new_id = slugify(new_name)
            if new_id != sj.id and d.find_subject(ws.id, pj.id, new_id) is not None:
                raise ValidationError(f"Subject já existe no project: {new_name}")
            for record in d.items_in(ws.id, pj.id, sj.id):
                d.put(dataclasses.replace(record, subject=new_name, updated_at=utcnow()))
            listed = d.meta(meta_location(ws.id, pj.id)).get("subjects") or []
            if any(_entry_id(e) == sj.id for e in listed):
                entry: Any = (
                    {"name": new_name, "description": sj.description}
                    if sj.description else new_name
                )
                _set_subject_meta(d, ws, pj, sj.id, entry)
            brain.commit(d, f"knowledge-os: renomeia subject {sj.name} -> {new_name}")
        logger.info("Subject renomeado: %s -> %s (project %s)", name, new_name, project_id)
        return brain.snapshot.subject(ws.id, pj.id, new_id)

    def merge(self, workspace_id: str, project_id: str, source: str, target: str) -> dict[str, int]:
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
            brain.commit(d, f"knowledge-os: mescla subject {src.name} em {tgt.name}")
        logger.info("Subject mesclado: %s -> %s (project %s)", source, target, project_id)
        return {"merged_items": len(records)}

    def delete(self, workspace_id: str, project_id: str, name: str) -> bool:
        """Remove o subject, deixando os itens dele sem subject. False se não existe."""
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, project_id)
            sj = d.find_subject(ws.id, pj.id, name)
            if sj is None:
                logger.debug("Subject inexistente para delete: %s", name)
                return False
            for record in d.items_in(ws.id, pj.id, sj.id):
                d.put(dataclasses.replace(record, subject=None, updated_at=utcnow()))
            _set_subject_meta(d, ws, pj, sj.id, None)
            brain.commit(d, f"knowledge-os: remove subject {pj.name}/{sj.name}")
        logger.info("Subject removido: %s", name)
        return True
