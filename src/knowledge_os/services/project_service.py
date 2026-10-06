"""Project service: CRUD e export (import será feito em T5)."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_os.db.models import Project, Workspace
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services._common import (
    EXPORT_VERSION,
    item_to_dict,
    project_to_dict,
    session_scope,
    tiebreak,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


def _merge_project_contents(s: Session, src: Project, tgt: Project) -> dict[str, int]:
    """Move items/subjects de `src` para `tgt` (mesma sessão) e apaga `src`. Sem commit final.

    Subjects homônimos: items repointados pro subject de `tgt`, duplicado de `src` apagado.
    Demais subjects: mudam de dono (project_id = tgt.id), mantendo histórico.
    """
    from sqlalchemy import delete, update

    from knowledge_os.db.models import Item, RepoLink, Subject

    # Bulk updates/deletes direto (sem passar pela coleção `project.subjects`): a cascade
    # "delete-orphan" entre Project e Subject apagaria subjects só repontados de dono.
    target_subject_names: dict[str, str] = dict(
        s.execute(select(Subject.name, Subject.id).where(Subject.project_id == tgt.id)).all()
    )
    src_subjects = list(
        s.execute(select(Subject.id, Subject.name).where(Subject.project_id == src.id)).all()
    )
    merged_subjects = 0
    for sub_id, sub_name in src_subjects:
        if sub_name in target_subject_names:
            # Repointa antes de apagar o duplicado; o project_id desses items já será
            # atualizado abaixo, junto com os demais items do project de origem.
            s.execute(
                update(Item)
                .where(Item.subject_id == sub_id)
                .values(subject_id=target_subject_names[sub_name])
            )
            s.execute(delete(Subject).where(Subject.id == sub_id))
        else:
            s.execute(update(Subject).where(Subject.id == sub_id).values(project_id=tgt.id))
            merged_subjects += 1
    merged_items = (
        s.execute(
            update(Item)
            .where(Item.project_id == src.id)
            .values(project_id=tgt.id, workspace_id=tgt.workspace_id)
        ).rowcount  # type: ignore[attr-defined]
        or 0
    )
    s.execute(delete(RepoLink).where(RepoLink.project_id == src.id))
    s.delete(src)
    s.commit()
    logger.info("Project mesclado: %s -> %s", src.name, tgt.name)
    return {"merged_items": merged_items, "merged_subjects": merged_subjects}


class ProjectService:
    """Operações sobre projects.

    Se `session` não for informada, cada operação abre uma sessão própria
    via get_session(get_engine()).
    """

    def __init__(
        self, session: Session | None = None, connection_id: str | None = None
    ) -> None:
        self._session = session
        self._connection_id = connection_id

    def _find(self, s: Session, workspace_id: str, name: str) -> Project | None:
        return s.scalar(
            select(Project).where(Project.workspace_id == workspace_id, Project.name == name)
        )

    def create(self, workspace_id: str, name: str, description: str | None = None) -> Project:
        """Cria um project. NotFoundError se workspace não existe; ValidationError se duplicado."""
        with session_scope(self._session, self._connection_id) as s:
            if s.get(Workspace, workspace_id) is None:
                raise NotFoundError(f"Workspace não encontrado: {workspace_id}")
            if self._find(s, workspace_id, name) is not None:
                raise ValidationError(f"Project já existe no workspace: {name}")
            dm = Project(
                id=str(uuid.uuid4()), workspace_id=workspace_id, name=name, description=description
            )
            s.add(dm)
            s.commit()
            s.refresh(dm)
            logger.info("Project criado: %s (workspace %s)", name, workspace_id)
            return dm

    def list(self, workspace_id: str) -> list[Project]:
        """Lista os projects de um workspace ordenados por created_at."""
        with session_scope(self._session, self._connection_id) as s:
            rows = list(
                s.scalars(
                    select(Project)
                    .where(Project.workspace_id == workspace_id)
                    .order_by(Project.created_at, *tiebreak(s, "projects"))
                )
            )
            logger.debug("%d projects listados", len(rows))
            return rows

    def get(self, workspace_id: str, name: str) -> Project:
        """Obtém project por nome. Levanta NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                raise NotFoundError(f"Project não encontrado: {name}")
            return dm

    def rename(self, workspace_id: str, name: str, new_name: str) -> Project:
        """Renomeia um project dentro do workspace. ValidationError se new_name já existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                raise NotFoundError(f"Project não encontrado: {name}")
            if new_name != name and self._find(s, workspace_id, new_name) is not None:
                raise ValidationError(f"Project já existe no workspace: {new_name}")
            dm.name = new_name
            s.commit()
            s.refresh(dm)
            logger.info("Project renomeado: %s -> %s (workspace %s)", name, new_name, workspace_id)
            return dm

    def merge(self, workspace_id: str, source: str, target: str) -> dict[str, int]:
        """Move os items de source para target e apaga source (mesmo workspace).

        Subjects homônimos são mesclados (items repointados, duplicado apagado); os demais
        mudam de dono (project_id = target).
        """
        with session_scope(self._session, self._connection_id) as s:
            src = self._find(s, workspace_id, source)
            if src is None:
                raise NotFoundError(f"Project não encontrado: {source}")
            tgt = self._find(s, workspace_id, target)
            if tgt is None:
                raise NotFoundError(f"Project não encontrado: {target}")
            if src.id == tgt.id:
                raise ValidationError("source e target são o mesmo project")
            return _merge_project_contents(s, src, tgt)

    def delete(self, workspace_id: str, name: str) -> bool:
        """Remove project (e seus items). False se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                logger.debug("Project inexistente para delete: %s", name)
                return False
            from sqlalchemy import delete, select

            from knowledge_os.db.models import Item, RepoLink
            from knowledge_os.services._common import purge_item_links

            purge_item_links(s, list(s.scalars(select(Item.id).where(Item.project_id == dm.id))))
            s.execute(delete(RepoLink).where(RepoLink.project_id == dm.id))
            s.delete(dm)
            s.commit()
            logger.info("Project removido: %s", name)
            return True

    def export(self, workspace_id: str, name: str) -> dict[str, Any]:
        """Retorna {project_data} com o project e seus items."""
        with session_scope(self._session, self._connection_id) as s:
            dm = self._find(s, workspace_id, name)
            if dm is None:
                logger.error("Export de project inexistente: %s", name)
                raise NotFoundError(f"Project não encontrado: {name}")
            items = [item_to_dict(i) for i in sorted(dm.items, key=lambda i: i.created_at or 0)]
            logger.info("Project exportado: %s", name)
            return {
                "project_data": {
                    "version": EXPORT_VERSION,
                    "exported_at": utc_now_iso(),
                    "project": project_to_dict(dm),
                    "items": items,
                }
            }
