"""Projetos: liga um repositório (remote do git ou caminho) a um workspace/domain."""

import re
import subprocess
from pathlib import Path

from sqlalchemy import Engine, select

from knowledge_os.db.models import Domain, RepoLink, Workspace
from knowledge_os.db.session import get_engine, get_session
from knowledge_os.db.timeutil import utcnow
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.item_service import ItemService

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


COMMON_DOMAIN = "Geral"  # em cada workspace: o que vale para todos os seus repositórios
LOCAL_WORKSPACE = "Pessoal"  # repositório sem remote


def repo_name(key: str) -> str:
    """Nome do repositório (último trecho da chave): o domain padrão do projeto."""
    return key.removeprefix("path:").rstrip("/").rsplit("/", 1)[-1] or key


def owner_prefix(key: str) -> str | None:
    """`github.com/org/repo` → `github.com/org/` (prefixo do dono); sem remote, None."""
    if key.startswith("path:") or key.count("/") < 2:
        return None
    return key.rsplit("/", 1)[0] + "/"


def owner_name(key: str) -> str:
    """Workspace padrão do primeiro repo de um dono: o nome do dono no remote."""
    prefix = owner_prefix(key)
    return prefix.rstrip("/").rsplit("/", 1)[-1] if prefix else LOCAL_WORKSPACE


def repo_key(repo: str) -> str:
    """Chave estável do repositório: o remote normalizado ou, sem remote, o caminho da raiz.

    Aceita um caminho (qualquer pasta dentro do repositório), uma URL de remote ou uma
    chave já normalizada.
    """
    repo = repo.strip()
    if not repo:
        raise ValidationError("project vazio")
    if repo.startswith("path:"):
        return repo
    looks_remote = bool(_SCHEME.match(repo)) or re.match(r"^[^/\\\s]+@[^:]+:", repo)
    path = Path(repo).expanduser()
    if not looks_remote and path.exists():
        root = _git_root(path.resolve()) or path.resolve()
        remote = _git_remote(root)
        if remote:
            return normalize_remote(remote)
        return "path:" + root.as_posix().lower()
    if looks_remote or "/" in repo:
        return normalize_remote(repo)
    raise ValidationError(f"Projeto não reconhecido (caminho inexistente?): {repo}")


class RepoService:
    """Ligações projeto → workspace/domain no banco da connection."""

    def __init__(self, engine: Engine | None = None, connection_id: str | None = None) -> None:
        self._engine = engine
        self._connection_id = connection_id

    def _get_engine(self) -> Engine:
        return self._engine if self._engine is not None else get_engine(self._connection_id)

    def link(
        self, repo: str, workspace: str | None = None, domain: str | None = None
    ) -> dict[str, str]:
        """Liga (ou religa) o repositório; workspace e domain são criados se não existirem.

        Workspace = contexto de trabalho (empresa, cliente, pessoal); domain = o repositório.
        Sem workspace: o de outro repo do mesmo dono já ligado; senão o nome do dono no
        remote (sem remote, `Pessoal`). Sem domain: o nome do repositório. O domain `Geral`
        de cada workspace e o workspace `Global` guardam o que vale para mais de um repo.
        """
        key = repo_key(repo)
        workspace = workspace or self._sibling_workspace(key) or owner_name(key)
        domain = domain or repo_name(key)
        ws_id, dm_id = ItemService(self._engine, self._connection_id).ensure_location(
            workspace, domain
        )
        session = get_session(self._get_engine())
        try:
            row = session.get(RepoLink, key)
            if row is None:
                session.add(RepoLink(repo_key=key, workspace_id=ws_id, domain_id=dm_id))
            else:
                row.workspace_id, row.domain_id = ws_id, dm_id
                row.updated_at = utcnow()
            session.commit()
        finally:
            session.close()
        return {"repo_key": key, "workspace": workspace, "domain": domain}

    def _sibling_workspace(self, key: str) -> str | None:
        """Workspace de outro repositório do mesmo dono já ligado (o mais recente)."""
        prefix = owner_prefix(key)
        if prefix is None:
            return None
        session = get_session(self._get_engine())
        try:
            return session.scalar(
                select(Workspace.name)
                .join(RepoLink, RepoLink.workspace_id == Workspace.id)
                .where(RepoLink.repo_key.startswith(prefix), RepoLink.repo_key != key)
                .order_by(RepoLink.updated_at.desc())
                .limit(1)
            )
        finally:
            session.close()

    def resolve(self, repo: str) -> dict[str, str] | None:
        """{repo_key, workspace_id, workspace, domain_id, domain} ou None se não ligado."""
        key = repo_key(repo)
        session = get_session(self._get_engine())
        try:
            row = session.execute(
                select(RepoLink, Workspace.name, Domain.name)
                .join(Workspace, Workspace.id == RepoLink.workspace_id)
                .join(Domain, Domain.id == RepoLink.domain_id)
                .where(RepoLink.repo_key == key)
            ).first()
        finally:
            session.close()
        if row is None:
            return None
        link, ws_name, dm_name = row
        return {
            "repo_key": key, "workspace_id": link.workspace_id, "workspace": ws_name,
            "domain_id": link.domain_id, "domain": dm_name,
        }

    def require(self, repo: str) -> dict[str, str]:
        found = self.resolve(repo)
        if found is None:
            raise NotFoundError(
                f"Projeto não ligado ao segundo cérebro: {repo_key(repo)}. "
                "Ligue com repo_link(repo, workspace, domain) ou rode /plumb-setup."
            )
        return found
