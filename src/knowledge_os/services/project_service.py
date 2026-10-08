"""Project service: criar, listar, renomear, mesclar, remover e exportar projects.

Um project é uma pasta dentro da do workspace (o slug do nome); nome de exibição, descrição e
os subjects sem item ficam no `.knowledge.yaml` dela.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import (
    EXPORT_VERSION,
    item_to_dict,
    project_to_dict,
    utc_now_iso,
)
from knowledge_os.services.brain import (
    Brain,
    Draft,
    Project,
    Workspace,
    check_name,
    is_published,
    meta_location,
    utcnow,
)
from knowledge_os.services.item_file import slugify
from knowledge_os.services.workspace_service import relink

logger = logging.getLogger(__name__)


def _subject_key(entry: Any) -> str:
    return slugify(entry if isinstance(entry, str) else str(entry.get("name") or ""))


def merge_project_in(
    d: Draft, src_ws: Workspace, src: Project, tgt_ws: Workspace, tgt: Project
) -> dict[str, int]:
    """Move os itens (e subjects) de `src` para `tgt` e apaga `src`, no rascunho.

    Subjects homônimos: os itens passam para o subject de `tgt`. Os demais vão junto com o
    nome que tinham.
    """
    target_subjects = {s.id: s.name for s in d.subjects(tgt_ws.id, tgt.id)}
    merged_subjects = sum(1 for s in d.subjects(src_ws.id, src.id) if s.id not in target_subjects)
    records = d.items_in(src_ws.id, src.id)
    for record in records:
        subject = record.subject
        if subject and slugify(subject) in target_subjects:
            subject = target_subjects[slugify(subject)]
        d.put(dataclasses.replace(record, workspace=tgt_ws.name, project=tgt.name,
                                  subject=subject, updated_at=utcnow()))
    src_rel, tgt_rel = meta_location(src_ws.id, src.id), meta_location(tgt_ws.id, tgt.id)
    if src_rel != tgt_rel:
        extra = [s for s in d.meta(src_rel).get("subjects") or []
                 if _subject_key(s) not in target_subjects]
        if extra:
            data = d.meta(tgt_rel)
            d.set_meta(tgt_rel, {"name": tgt.name, **data,
                                 "subjects": [*(data.get("subjects") or []), *extra]})
        d.set_meta(src_rel, None)
    return {"merged_items": len(records), "merged_subjects": merged_subjects}


class ProjectService:
    """Operações sobre os projects da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def _brain(self) -> Brain:
        return Brain(self._connection_id)

    def create(self, workspace_id: str, name: str, description: str | None = None) -> Project:
        """Cria um project. NotFoundError se workspace não existe; ValidationError se duplicado."""
        name = check_name(name, "project")
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            if d.find_project(ws.id, slugify(name)) is not None:
                raise ValidationError(f"Project já existe no workspace: {name}")
            data: dict[str, Any] = {"name": name}
            if description is not None:
                data["description"] = description
            d.set_meta(meta_location(ws.id, slugify(name)), data)
            brain.commit(d, f"knowledge-os: cria project {ws.name}/{name}")
        logger.info("Project criado: %s (workspace %s)", name, workspace_id)
        return brain.snapshot.project(ws.id, slugify(name))

    def list(self, workspace_id: str) -> list[Project]:
        """Projects do workspace, por nome."""
        return self._brain().snapshot.projects(workspace_id)

    def list_all(self) -> list[Project]:
        """Projects de todos os workspaces."""
        return self._brain().snapshot.all_projects()

    def get(self, workspace_id: str, name: str) -> Project:
        """Project por nome ou id. NotFoundError se não existe."""
        return self._brain().snapshot.project(workspace_id, name)

    def find_by_id(self, project_id: str, workspace_id: str | None = None) -> Project:
        """Project pelo id; sem workspace, o id precisa ser único entre os workspaces."""
        snap = self._brain().snapshot
        if workspace_id:
            return snap.project(workspace_id, project_id)
        found = [p for p in snap.all_projects() if p.id == project_id]
        if not found:
            raise NotFoundError(f"Project não encontrado: {project_id}")
        if len(found) > 1:
            raise ValidationError(
                f"Project {project_id!r} existe em mais de um workspace: informe workspace_id"
            )
        return found[0]

    def rename(self, workspace_id: str, name: str, new_name: str) -> Project:
        """Renomeia um project dentro do workspace. ValidationError se new_name já existe."""
        return self.update(workspace_id, name, new_name)

    def update(
        self, workspace_id: str, ref: str, name: str, description: str | None = None
    ) -> Project:
        """Troca o nome (movendo a pasta, se o slug mudar) e, se informada, a descrição."""
        name = check_name(name, "project")
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, ref)
            new_id = slugify(name)
            if new_id != pj.id and d.find_project(ws.id, new_id) is not None:
                raise ValidationError(f"Project já existe no workspace: {name}")
            for record in d.items_in(ws.id, pj.id):
                d.put(dataclasses.replace(record, project=name))
            meta = d.meta(meta_location(ws.id, pj.id))
            if new_id != pj.id:
                d.set_meta(meta_location(ws.id, pj.id), None)
            meta["name"] = name
            if description is not None:
                meta["description"] = description
            d.set_meta(meta_location(ws.id, new_id), meta)
            result = brain.commit(d, f"knowledge-os: atualiza project {ws.name}/{name}")
        if not is_published(result):
            # Em revisão: a pasta e a ligação dos repositórios só mudam depois do merge.
            return Project(new_id, ws.id, name, meta.get("description"), pj.created_at,
                           pj.updated_at)
        relink(brain.cid, ws.id, pj.id, workspace=ws.name, project=name)
        logger.info("Project atualizado: %s -> %s (workspace %s)", ref, name, workspace_id)
        return brain.snapshot.project(ws.id, new_id)

    def merge(self, workspace_id: str, source: str, target: str) -> dict[str, int]:
        """Move os itens de source para target e apaga source (mesmo workspace).

        Subjects homônimos são mesclados; os demais passam para target com o mesmo nome.
        """
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            src = d.project(ws.id, source)
            tgt = d.project(ws.id, target)
            if src.id == tgt.id:
                raise ValidationError("source e target são o mesmo project")
            result = merge_project_in(d, ws, src, ws, tgt)
            published = is_published(
                brain.commit(d, f"knowledge-os: mescla project {src.name} em {tgt.name}")
            )
        if published:
            relink(brain.cid, ws.id, src.id, workspace=ws.name, project=tgt.name)
        logger.info("Project mesclado: %s -> %s", source, target)
        return result

    def delete(self, workspace_id: str, name: str) -> bool:
        """Remove project (e seus itens). False se não existe."""
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.find_project(ws.id, name)
            if pj is None:
                logger.debug("Project inexistente para delete: %s", name)
                return False
            removed = [r.id for r in d.items_in(ws.id, pj.id)]
            for record_id in removed:
                d.remove(record_id)
            d.set_meta(meta_location(ws.id, pj.id), None)
            result = brain.commit(d, f"knowledge-os: remove project {ws.name}/{pj.name}")
        if is_published(result):
            # Em revisão (PR/Issue) o project continua na pasta: valor e ligação ficam.
            for record_id in removed:
                brain.secret_path(record_id).unlink(missing_ok=True)
            relink(brain.cid, ws.id, pj.id, workspace=None)
        logger.info("Project removido: %s", name)
        return True

    def export(self, workspace_id: str, name: str) -> dict[str, Any]:
        """Retorna {project_data} com o project e seus itens."""
        brain = self._brain()
        snap = brain.snapshot
        pj = snap.find_project(workspace_id, name)
        if pj is None:
            raise NotFoundError(f"Project não encontrado: {name}")
        records = sorted(snap.items_in(pj.workspace_id, pj.id),
                         key=lambda r: (r.created_at, r.path))
        return {
            "project_data": {
                "version": EXPORT_VERSION,
                "exported_at": utc_now_iso(),
                "project": project_to_dict(pj),
                "items": [item_to_dict(i) for i in brain.views(records)],
            }
        }
