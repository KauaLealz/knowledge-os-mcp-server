"""Projetos: liga um repositório (remote do git ou caminho) a um workspace/project.

A ligação é desta máquina (`storage.local_state`, `repos.json` no home) e aponta para uma
conexão: cada `RepoService` só enxerga as ligações da sua conexão.
"""

import re
import subprocess
from pathlib import Path
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.item_file import slugify
from knowledge_os.storage import local_state
from knowledge_os.storage.access import resolve_connection
from knowledge_os.storage.search import strip_accents

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


COMMON_PROJECT = "Geral"  # em cada workspace: o que vale para todos os seus repositórios
LOCAL_WORKSPACE = "Pessoal"  # repositório sem remote


def repo_name(key: str) -> str:
    """Nome do repositório (último trecho da chave): o project padrão do projeto."""
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
    """Ligações projeto → workspace/project da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def _cid(self) -> str:
        return resolve_connection(self._connection_id).id

    def _links(self) -> dict[str, dict[str, Any]]:
        cid = self._cid()
        return {k: v for k, v in local_state.list_repos().items()
                if v.get("connection_id") == cid}

    def link(
        self,
        repo: str,
        workspace: str | None = None,
        project: str | None = None,
        confirm_new: bool = False,
    ) -> dict[str, Any]:
        """Liga (ou religa) o repositório; workspace e project passam a existir se faltarem.

        Workspace = contexto de trabalho (empresa, cliente, pessoal); project = o repositório.
        Sem workspace: o de outro repo do mesmo dono já ligado; senão o nome do dono no
        remote (sem remote, `Pessoal`). Sem project: o nome do repositório. O project `Geral`
        de cada workspace e o workspace `Global` guardam o que vale para mais de um repo.

        Sem `confirm_new`: se o nome candidato de workspace ou project (depois de
        casefold + sem acento) bater com um já existente mas com grafia diferente, não cria
        nada — devolve {status: "candidate", candidate_match: {...}} para o chamador confirmar.
        """
        from knowledge_os.services.brain import Brain
        from knowledge_os.services.item_service import ItemService

        key = repo_key(repo)
        cid = self._cid()
        workspace = workspace or self._sibling_workspace(key) or owner_name(key)
        project = project or repo_name(key)
        if not confirm_new:
            candidate = self._find_candidate(Brain(cid), workspace, project)
            if candidate is not None:
                return {"status": "candidate", "candidate_match": candidate}
        ws_id, pj_id = ItemService(cid).ensure_location(workspace, project)
        snap = Brain(cid).snapshot
        ws_name = snap.workspace(ws_id).name
        pj_name = snap.project(ws_id, pj_id).name
        local_state.set_repo(key, connection_id=cid, workspace=ws_name, project=pj_name)
        return {"repo_key": key, "workspace": ws_name, "project": pj_name}

    @staticmethod
    def _norm(name: str) -> str:
        return strip_accents(name).casefold()

    def _find_candidate(self, brain: Any, workspace: str, project: str) -> dict[str, str] | None:
        """Nome candidato de workspace/project parecido (casefold+sem acento) com um
        já existente, mas grafado diferente. Só sinaliza se o literal já não existir.
        """
        snap = brain.snapshot
        workspaces = snap.workspaces()
        existing_ws = next((w for w in workspaces if w.name == workspace), None)
        if existing_ws is None:
            norm_ws = self._norm(workspace)
            match = next(
                (w for w in workspaces
                 if self._norm(w.name) == norm_ws or w.id == slugify(workspace)),
                None,
            )
            if match is not None:
                return {"field": "workspace", "input": workspace, "candidate": match.name}
            return None
        projects = snap.projects(existing_ws.id)
        if any(p.name == project for p in projects):
            return None
        norm_pj = self._norm(project)
        match_pj = next(
            (p for p in projects if self._norm(p.name) == norm_pj or p.id == slugify(project)),
            None,
        )
        if match_pj is not None:
            return {"field": "project", "input": project, "candidate": match_pj.name}
        return None

    def _sibling_workspace(self, key: str) -> str | None:
        """Workspace de outro repositório do mesmo dono já ligado (o mais recente)."""
        prefix = owner_prefix(key)
        if prefix is None:
            return None
        siblings = [
            v for k, v in self._links().items() if k.startswith(prefix) and k != key
        ]
        if not siblings:
            return None
        return max(siblings, key=lambda v: v.get("updated_at") or "").get("workspace")

    def resolve(self, repo: str) -> dict[str, str] | None:
        """{repo_key, workspace_id, workspace, project_id, project} ou None se não ligado."""
        key = repo_key(repo)
        entry = self._links().get(key)
        if entry is None:
            return None
        ws, pj = entry.get("workspace") or "", entry.get("project") or ""
        return {
            "repo_key": key, "workspace_id": slugify(ws), "workspace": ws,
            "project_id": slugify(pj), "project": pj,
        }

    def require(self, repo: str) -> dict[str, str]:
        found = self.resolve(repo)
        if found is None:
            raise NotFoundError(
                f"Projeto não ligado ao segundo cérebro: {repo_key(repo)}. "
                'Ligue com repo(action="link", repo=..., workspace=..., project=...) '
                "ou rode /plumb-setup."
            )
        return found

    def list_links(
        self, workspace: str | None = None, project: str | None = None
    ) -> list[dict[str, str]]:
        """Ligações da conexão, opcionalmente filtradas por workspace e/ou project (nome ou id)."""
        out = []
        for key, entry in sorted(self._links().items()):
            ws, pj = entry.get("workspace") or "", entry.get("project") or ""
            if workspace and slugify(ws) != slugify(workspace):
                continue
            if project and slugify(pj) != slugify(project):
                continue
            out.append({"repo_key": key, "workspace": ws, "project": pj})
        return out

    def unlink(self, repo: str) -> bool:
        """Apaga o vínculo do repositório. NotFoundError se não existir."""
        key = repo_key(repo)
        if key not in self._links():
            raise NotFoundError(f"Projeto não ligado ao segundo cérebro: {key}")
        local_state.delete_repo(key)
        return True
