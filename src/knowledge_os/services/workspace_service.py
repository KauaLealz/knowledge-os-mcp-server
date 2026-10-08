"""Workspace service: criar, listar, renomear, mesclar, remover e exportar workspaces.

Um workspace é uma pasta da conexão (o slug do nome); o nome de exibição e a descrição ficam
no `.knowledge.yaml` dela. Renomear, mesclar e remover regravam/movem os arquivos dos itens e
publicam tudo de uma vez.
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
    workspace_to_dict,
)
from knowledge_os.services.brain import (
    Brain,
    Draft,
    Workspace,
    check_name,
    is_published,
    meta_location,
    utcnow,
)
from knowledge_os.services.item_file import slugify
from knowledge_os.storage import local_state

logger = logging.getLogger(__name__)


def relink(connection_id: str, ws_id: str, pj_id: str | None, *, workspace: str | None,
           project: str | None = None) -> None:
    """Repositórios ligados a `ws_id` (e `pj_id`, se informado) passam para `workspace`/`project`.

    `workspace=None` desfaz a ligação (o lugar deixou de existir).
    """
    for key, entry in local_state.list_repos().items():
        if entry.get("connection_id") != connection_id:
            continue
        if slugify(entry.get("workspace") or "") != ws_id:
            continue
        if pj_id is not None and slugify(entry.get("project") or "") != pj_id:
            continue
        if workspace is None:
            local_state.delete_repo(key)
        else:
            local_state.set_repo(key, connection_id=connection_id, workspace=workspace,
                                 project=project or entry.get("project") or "")


def move_project_metas(d: Draft, ws_from: str, ws_to: str) -> None:
    """Leva os `.knowledge.yaml` dos projects de um workspace para outro (sem sobrescrever)."""
    prefix = f"{ws_from}/"
    for rel in [r for r in d.metas if r.startswith(prefix) and r.count("/") == 2]:
        pj_id = rel.split("/")[1]
        data = d.meta(rel)
        target = meta_location(ws_to, pj_id)
        if target in d.metas:
            merged = d.meta(target)
            names = {slugify(s if isinstance(s, str) else s.get("name", ""))
                     for s in merged.get("subjects") or []}
            extra = [s for s in data.get("subjects") or []
                     if slugify(s if isinstance(s, str) else s.get("name", "")) not in names]
            if extra:
                merged["subjects"] = [*(merged.get("subjects") or []), *extra]
                d.set_meta(target, merged)
        else:
            d.set_meta(target, data)
        if rel != target:
            d.set_meta(rel, None)


class WorkspaceService:
    """Operações sobre os workspaces da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def _brain(self) -> Brain:
        return Brain(self._connection_id)

    def create(self, name: str, description: str | None = None) -> Workspace:
        """Cria um workspace. Levanta ValidationError se o nome (ou o slug dele) já existe."""
        name = check_name(name, "workspace")
        brain = self._brain()
        with brain.editing() as d:
            if d.find_workspace(slugify(name)) is not None:
                raise ValidationError(f"Workspace já existe: {name}")
            data: dict[str, Any] = {"name": name}
            if description is not None:
                data["description"] = description
            d.set_meta(meta_location(slugify(name)), data)
            brain.commit(d, f"knowledge-os: cria workspace {name}")
        logger.info("Workspace criado: %s", name)
        return brain.snapshot.workspace(slugify(name))

    def list(self) -> list[Workspace]:
        """Workspaces por nome."""
        return self._brain().snapshot.workspaces()

    def get(self, name: str) -> Workspace:
        """Workspace por nome ou id. NotFoundError se não existe."""
        return self._brain().snapshot.workspace(name)

    def update(self, ref: str, name: str, description: str | None = None) -> Workspace:
        """Troca o nome (movendo a pasta, se o slug mudar) e, se informada, a descrição."""
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(ref)
            new = self._rename_in(d, ws, check_name(name, "workspace"))
            if description is not None:
                rel = meta_location(slugify(new))
                d.set_meta(rel, {**d.meta(rel), "name": new, "description": description})
            result = brain.commit(d, f"knowledge-os: atualiza workspace {new}")
        if not is_published(result):
            return Workspace(slugify(new), new, description or ws.description, ws.created_at,
                             ws.updated_at)
        relink(brain.cid, ws.id, None, workspace=new)
        return brain.snapshot.workspace(slugify(new))

    def rename(self, name: str, new_name: str) -> Workspace:
        """Renomeia um workspace. ValidationError se new_name já existe."""
        new_name = check_name(new_name, "workspace")
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(name)
            self._rename_in(d, ws, new_name)
            result = brain.commit(
                d, f"knowledge-os: renomeia workspace {ws.name} -> {new_name}"
            )
        if not is_published(result):
            # Em revisão: a pasta e a ligação dos repositórios só mudam depois do merge.
            return Workspace(slugify(new_name), new_name, ws.description, ws.created_at,
                             ws.updated_at)
        relink(brain.cid, ws.id, None, workspace=new_name)
        logger.info("Workspace renomeado: %s -> %s", name, new_name)
        return brain.snapshot.workspace(slugify(new_name))

    @staticmethod
    def _rename_in(d: Draft, ws: Workspace, new_name: str) -> str:
        new_id = slugify(new_name)
        if new_id != ws.id and d.find_workspace(new_id) is not None:
            raise ValidationError(f"Workspace já existe: {new_name}")
        for record in d.items_in(ws.id):
            d.put(dataclasses.replace(record, workspace=new_name))
        meta = d.meta(meta_location(ws.id))
        if new_id != ws.id:
            move_project_metas(d, ws.id, new_id)
            d.set_meta(meta_location(ws.id), None)
        d.set_meta(meta_location(new_id), {**meta, "name": new_name})
        return new_name

    def merge(self, source: str, target: str) -> dict[str, int]:
        """Move todos os projects de source para target e apaga source.

        Projects homônimos (mesmo nome em source e target) são mesclados (itens e subjects
        juntos) em vez de duplicados. Repositórios ligados a source passam para target.
        """
        from knowledge_os.services.project_service import merge_project_in

        brain = self._brain()
        with brain.editing() as d:
            src = d.workspace(source)
            tgt = d.workspace(target)
            if src.id == tgt.id:
                raise ValidationError("source e target são o mesmo workspace")
            merged_projects = renamed_collisions = 0
            for project in d.projects(src.id):
                existing = d.find_project(tgt.id, project.id)
                if existing is not None:
                    merge_project_in(d, src, project, tgt, existing)
                    renamed_collisions += 1
                else:
                    for record in d.items_in(src.id, project.id):
                        d.put(dataclasses.replace(record, workspace=tgt.name,
                                                  updated_at=utcnow()))
                merged_projects += 1
            move_project_metas(d, src.id, tgt.id)
            d.set_meta(meta_location(src.id), None)
            result = brain.commit(d, f"knowledge-os: mescla workspace {src.name} em {tgt.name}")
        if is_published(result):
            relink(brain.cid, src.id, None, workspace=tgt.name)
        logger.info("Workspace mesclado: %s -> %s", source, target)
        return {"merged_projects": merged_projects, "renamed_collisions": renamed_collisions}

    def delete(self, name: str) -> bool:
        """Remove o workspace (projects e itens). False se não existe."""
        brain = self._brain()
        with brain.editing() as d:
            ws = d.find_workspace(name)
            if ws is None:
                logger.debug("Workspace inexistente para delete: %s", name)
                return False
            removed = [r.id for r in d.items_in(ws.id)]
            for record_id in removed:
                d.remove(record_id)
            for rel in [r for r in d.metas if r.startswith(f"{ws.id}/")]:
                d.set_meta(rel, None)
            result = brain.commit(d, f"knowledge-os: remove workspace {ws.name}")
        if is_published(result):
            # Em revisão (PR/Issue) o workspace continua na pasta: valor e ligação ficam.
            for record_id in removed:
                brain.secret_path(record_id).unlink(missing_ok=True)
            relink(brain.cid, ws.id, None, workspace=None)
        logger.info("Workspace removido: %s", name)
        return True

    def export(self, name: str) -> dict[str, Any]:
        """Retorna {manifest, workspace_data} pronto para empacotar em ZIP."""
        brain = self._brain()
        snap = brain.snapshot
        ws = snap.find_workspace(name)
        if ws is None:
            raise NotFoundError(f"Workspace não encontrado: {name}")
        projects = [project_to_dict(p) for p in snap.projects(ws.id)]
        records = sorted(snap.items_in(ws.id), key=lambda r: (r.created_at, r.path))
        items = [item_to_dict(i) for i in brain.views(records)]
        return {
            "manifest": {
                "version": EXPORT_VERSION,
                "type": "workspace",
                "name": ws.name,
                "exported_at": utc_now_iso(),
                "counts": {"projects": len(projects), "items": len(items)},
            },
            "workspace_data": {
                "workspace": workspace_to_dict(ws),
                "projects": projects,
                "items": items,
            },
        }
