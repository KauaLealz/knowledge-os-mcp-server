"""Project service: criar, listar, atualizar (nome, descrição, scope), mesclar e remover.

Um project é uma pasta dentro da do workspace (o slug do nome); nome de exibição, descrição,
`scope` explícito e os subjects (`[{name, description?, scope?}]`) ficam no `.knowledge.yaml`
dela. Ao mover um project (merge de workspace) o scope vai junto; ao mesclar dois, vale o do
destino para o project — mas o item que herdava e mudaria de alcance ganha o scope de antes
como explícito (`Draft.keep_scopes`), para ninguém mudar de alcance sem pedir. `scope` segue a
convenção de `workspace_service` (None / valor / `""`).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
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
from knowledge_os.services.workspace_service import (
    apply_meta,
    check_scope,
    effective,
    relink,
)

logger = logging.getLogger(__name__)


def _subject_key(entry: Any) -> str:
    return slugify(entry if isinstance(entry, str) else str(entry.get("name") or ""))


def merge_project_in(
    d: Draft, src_ws: Workspace, src: Project, tgt_ws: Workspace, tgt: Project
) -> dict[str, Any]:
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

    def create(self, workspace_id: str, name: str, description: str | None = None,
               scope: str | None = None) -> Project:
        """Cria um project. NotFoundError se workspace não existe; ValidationError se duplicado
        ou se o scope não é um de `SCOPES`."""
        scope = check_scope(scope or None)
        name = check_name(name, "project")
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            if d.find_project(ws.id, slugify(name)) is not None:
                raise ValidationError(f"Project já existe no workspace: {name}")
            data = apply_meta({"name": name}, description, scope)
            d.set_meta(meta_location(ws.id, slugify(name)), data)
            brain.commit(d, f"knowledge-os: cria project {ws.name}/{name}")
        logger.info("Project criado: %s (workspace %s)", name, workspace_id)
        return brain.snapshot.project(ws.id, slugify(name))

    def list(self, workspace_id: str) -> list[Project]:
        """Projects do workspace, por nome."""
        return self._brain().snapshot.projects(workspace_id)

    def rows(self, workspace: str) -> list[dict[str, Any]]:
        """Para `project_list`/API: `[{id, workspace_id, name, description, scope,
        scope_explicit, items, subjects: [nomes]}]` por nome (`scope` = o que vale, com a
        herança do workspace)."""
        snap = self._brain().snapshot
        ws = snap.workspace(workspace)
        counts: dict[str, int] = {}
        for record in snap.items_in(ws.id):
            pj_id = slugify(record.project or "")
            counts[pj_id] = counts.get(pj_id, 0) + 1
        return [{"id": pj.id, "workspace_id": ws.id, "name": pj.name,
                 "description": pj.description, "scope": effective(pj.scope, ws.scope),
                 "scope_explicit": pj.scope, "items": counts.get(pj.id, 0),
                 "subjects": [sj.name for sj in snap.subjects(ws.id, pj.id)]}
                for pj in snap.projects(ws.id)]

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

    def update(self, workspace_id: str, ref: str, new_name: str | None = None,
               description: str | None = None, scope: str | None = None) -> Project:
        """Troca o nome (movendo a pasta, se o slug mudar), a descrição e/ou o scope; o que
        vier None fica como está (`scope=""` volta a herdar)."""
        scope = check_scope(scope, clearable=True)
        name_given = check_name(new_name, "project") if new_name is not None else None
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(workspace_id)
            pj = d.project(ws.id, ref)
            name = name_given or pj.name
            new_id = slugify(name)
            if new_id != pj.id and d.find_project(ws.id, new_id) is not None:
                raise ValidationError(f"Project já existe no workspace: {name}")
            if name != pj.name:
                for record in d.items_in(ws.id, pj.id):
                    d.put(dataclasses.replace(record, project=name))
            meta = d.meta(meta_location(ws.id, pj.id))
            if new_id != pj.id:
                d.set_meta(meta_location(ws.id, pj.id), None)
            meta = apply_meta({**meta, "name": name}, description, scope)
            d.set_meta(meta_location(ws.id, new_id), meta)
            result = brain.commit(d, f"knowledge-os: atualiza project {ws.name}/{name}")
        if not is_published(result):
            # Em revisão: a pasta e a ligação dos repositórios só mudam depois do merge.
            return Project(new_id, ws.id, name, meta.get("description"), pj.created_at,
                           pj.updated_at, meta.get("scope"))
        if name != pj.name:
            relink(brain.cid, ws.id, pj.id, workspace=ws.name, project=name)
        logger.info("Project atualizado: %s -> %s (workspace %s)", ref, name, workspace_id)
        return brain.snapshot.project(ws.id, new_id)

    def merge(self, workspace_id: str, source: str, target: str) -> dict[str, Any]:
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
            result["scope_changes"] = {"items": d.keep_scopes()}
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
