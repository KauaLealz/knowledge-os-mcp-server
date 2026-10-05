"""Projetos: liga um repositório (remote do git ou caminho) a um workspace/domain."""

import re
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, select

from src.db.models import Domain, ProjectLink, Workspace
from src.db.session import get_engine, get_session
from src.exceptions import NotFoundError, ValidationError
from src.services.item_service import ItemService

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")


def normalize_remote(remote: str) -> str:
    """`git@github.com:Org/Repo.git` e `https://github.com/org/repo` → `github.com/org/repo`."""
    value = remote.strip()
    value = _SCHEME.sub("", value)
    value = re.sub(r"^[^@/]+@", "", value)  # usuário (git@, token@)
    if ":" in value and "/" not in value.split(":", 1)[0]:
        value = value.replace(":", "/", 1)  # forma scp do ssh
    value = re.sub(r"\.git/?$", "", value).rstrip("/")
    return value.lower()


def _git_root(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_remote(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def project_key(project: str) -> str:
    """Chave estável do projeto: o remote normalizado ou, sem remote, o caminho da raiz.

    Aceita um caminho (qualquer pasta dentro do repositório), uma URL de remote ou uma
    chave já normalizada.
    """
    project = project.strip()
    if not project:
        raise ValidationError("project vazio")
    if project.startswith("path:"):
        return project
    looks_remote = bool(_SCHEME.match(project)) or re.match(r"^[^/\\\s]+@[^:]+:", project)
    path = Path(project).expanduser()
    if not looks_remote and path.exists():
        root = _git_root(path.resolve()) or path.resolve()
        remote = _git_remote(root)
        if remote:
            return normalize_remote(remote)
        return "path:" + root.as_posix().lower()
    if looks_remote or "/" in project:
        return normalize_remote(project)
    raise ValidationError(f"Projeto não reconhecido (caminho inexistente?): {project}")


class ProjectService:
    """Ligações projeto → workspace/domain no banco da connection."""

    def __init__(self, engine: Engine | None = None, connection_id: str | None = None) -> None:
        self._engine = engine
        self._connection_id = connection_id

    def _get_engine(self) -> Engine:
        return self._engine if self._engine is not None else get_engine(self._connection_id)

    def link(self, project: str, workspace: str, domain: str) -> dict[str, str]:
        """Liga (ou religa) o projeto; workspace e domain são criados se não existirem."""
        key = project_key(project)
        ws_id, dm_id = ItemService(self._engine, self._connection_id).ensure_location(
            workspace, domain
        )
        session = get_session(self._get_engine())
        try:
            row = session.get(ProjectLink, key)
            if row is None:
                session.add(ProjectLink(project_key=key, workspace_id=ws_id, domain_id=dm_id))
            else:
                row.workspace_id, row.domain_id = ws_id, dm_id
                row.updated_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()
        return {"project_key": key, "workspace": workspace, "domain": domain}

    def resolve(self, project: str) -> dict[str, str] | None:
        """{project_key, workspace_id, workspace, domain_id, domain} ou None se não ligado."""
        key = project_key(project)
        session = get_session(self._get_engine())
        try:
            row = session.execute(
                select(ProjectLink, Workspace.name, Domain.name)
                .join(Workspace, Workspace.id == ProjectLink.workspace_id)
                .join(Domain, Domain.id == ProjectLink.domain_id)
                .where(ProjectLink.project_key == key)
            ).first()
        finally:
            session.close()
        if row is None:
            return None
        link, ws_name, dm_name = row
        return {
            "project_key": key, "workspace_id": link.workspace_id, "workspace": ws_name,
            "domain_id": link.domain_id, "domain": dm_name,
        }

    def require(self, project: str) -> dict[str, str]:
        found = self.resolve(project)
        if found is None:
            raise NotFoundError(
                f"Projeto não ligado ao segundo cérebro: {project_key(project)}. "
                "Ligue com project_link(project, workspace, domain) ou rode /plumb-setup."
            )
        return found
