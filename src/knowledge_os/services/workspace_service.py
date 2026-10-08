"""Workspace service: criar, listar, atualizar (nome, descrição, scope), mesclar e remover.

Um workspace é uma pasta da conexão (o slug do nome); o nome de exibição, a descrição e o
`scope` explícito ficam no `.knowledge.yaml` dela. O `scope` de workspace, project e subject é
herdado pelos itens que não definem o seu (`Snapshot.effective_scope`): mudar o scope muda o
alcance de tudo que herda, sem mover arquivo de item. Renomear, mesclar e remover
regravam/movem os arquivos dos itens e publicam tudo de uma vez.

`scope` nas operações: `None` = não define (create) / não muda (update); um de
`model.SCOPES` = grava explícito; `""` (só no update) = tira o explícito e volta a herdar.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from knowledge_os.exceptions import ValidationError
from knowledge_os.model import DEFAULT_SCOPE, SCOPES
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


def check_scope(value: Any, *, clearable: bool = False) -> str | None:
    """`scope` de workspace/project/subject: None (não define), um de `SCOPES` ou, com
    `clearable`, `""` (volta a herdar). ValidationError lista os válidos."""
    if value is None:
        return None
    if value == "" and clearable:
        return ""
    if value not in SCOPES:
        extra = ' (ou "" para voltar a herdar)' if clearable else ""
        raise ValidationError(f"scope inválido: {value!r}. Válidos: {', '.join(SCOPES)}{extra}")
    return str(value)


def apply_meta(data: dict[str, Any], description: str | None, scope: str | None
               ) -> dict[str, Any]:
    """Aplica descrição e scope (já validado por `check_scope`) a um dicionário de metadados."""
    if description is not None:
        data["description"] = description
    if scope == "":
        data.pop("scope", None)
    elif scope:
        data["scope"] = scope
    return data


def effective(*scopes: str | None) -> str:
    """Primeiro scope explícito da cadeia (do mais específico ao workspace)."""
    return next((s for s in scopes if s), DEFAULT_SCOPE)


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

    def create(self, name: str, description: str | None = None,
               scope: str | None = None) -> Workspace:
        """Cria um workspace. ValidationError se o nome (ou o slug dele) já existe ou se o
        scope não é um de `SCOPES`."""
        scope = check_scope(scope or None)
        name = check_name(name, "workspace")
        brain = self._brain()
        with brain.editing() as d:
            if d.find_workspace(slugify(name)) is not None:
                raise ValidationError(f"Workspace já existe: {name}")
            data = apply_meta({"name": name}, description, scope)
            d.set_meta(meta_location(slugify(name)), data)
            brain.commit(d, f"knowledge-os: cria workspace {name}")
        logger.info("Workspace criado: %s", name)
        return brain.snapshot.workspace(slugify(name))

    def list(self) -> list[Workspace]:
        """Workspaces por nome."""
        return self._brain().snapshot.workspaces()

    def rows(self) -> list[dict[str, Any]]:
        """Para `workspace_list`/API: `[{id, name, description, scope, scope_explicit, items,
        projects}]` por nome (`scope` = o que vale; `scope_explicit` = o do `.knowledge.yaml`)."""
        snap = self._brain().snapshot
        counts: dict[str, int] = {}
        for record in snap.records.values():
            ws_id = slugify(record.workspace or "")
            counts[ws_id] = counts.get(ws_id, 0) + 1
        return [{"id": ws.id, "name": ws.name, "description": ws.description,
                 "scope": effective(ws.scope), "scope_explicit": ws.scope,
                 "items": counts.get(ws.id, 0), "projects": len(snap.projects(ws.id))}
                for ws in snap.workspaces()]

    def get(self, name: str) -> Workspace:
        """Workspace por nome ou id. NotFoundError se não existe."""
        return self._brain().snapshot.workspace(name)

    def update(self, ref: str, new_name: str | None = None, description: str | None = None,
               scope: str | None = None) -> Workspace:
        """Troca o nome (movendo a pasta, se o slug mudar), a descrição e/ou o scope; o que
        vier None fica como está (`scope=""` volta a herdar)."""
        scope = check_scope(scope, clearable=True)
        new_name = check_name(new_name, "workspace") if new_name is not None else None
        brain = self._brain()
        with brain.editing() as d:
            ws = d.workspace(ref)
            name = self._rename_in(d, ws, new_name) if new_name is not None else ws.name
            rel = meta_location(slugify(name))
            d.set_meta(rel, apply_meta({**d.meta(rel), "name": name}, description, scope))
            result = brain.commit(d, f"knowledge-os: atualiza workspace {name}")
        if not is_published(result):
            # Em revisão: a pasta e a ligação dos repositórios só mudam depois do merge.
            kept = ws.scope if scope is None else (scope or None)
            return Workspace(slugify(name), name, description or ws.description, ws.created_at,
                             ws.updated_at, kept)
        if slugify(name) != ws.id or name != ws.name:
            relink(brain.cid, ws.id, None, workspace=name)
        logger.info("Workspace atualizado: %s -> %s", ref, name)
        return brain.snapshot.workspace(slugify(name))

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
