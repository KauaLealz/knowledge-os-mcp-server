"""Único módulo que chama `gh` (GitHub CLI) via subprocess.

Funções finas: um subprocess `gh` + parse do resultado. Nunca `shell=True` nem
interpolação de string em comando (injeção) — sempre lista de argumentos.
"""

import subprocess
from pathlib import Path

from knowledge_os.exceptions import GitError
from knowledge_os.services.secret_guard import find_secret

_TIMEOUT_S = 30


def _redact_stderr(stderr: str) -> str:
    """Mensagem de erro com o stderr oculto se tiver cara de token/segredo."""
    kind = find_secret(stderr)
    if kind:
        return f"(saída oculta: parece conter {kind})"
    return stderr.strip()


def is_authenticated() -> bool:
    """`gh auth status`: código de saída 0 = autenticado."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def has_push_access(owner_repo: str) -> bool | None:
    """`gh api repos/{owner_repo} --jq .permissions.push`.

    `None` quando a chamada falha ou vem omissa — "não sei"; quem chama decide o
    que fazer, não forçamos True/False.
    """
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{owner_repo}", "--jq", ".permissions.push"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if output == "true":
        return True
    if output == "false":
        return False
    return None


def pr_create(cwd: Path, title: str, body: str, base: str = "main") -> str:
    """`gh pr create --title ... --body ... --base ... --head <branch-atual>`.

    Devolve a URL do PR (stdout).
    """
    head = _current_branch(cwd)
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                base,
                "--head",
                head,
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"Falha ao rodar 'gh pr create': {exc}") from exc
    if result.returncode != 0:
        raise GitError(f"Falha ao criar PR: {_redact_stderr(result.stderr)}")
    return result.stdout.strip()


def issue_create(owner_repo: str, title: str, body: str) -> str:
    """`gh issue create --repo ... --title ... --body ...`. Devolve a URL da issue."""
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                owner_repo,
                "--title",
                title,
                "--body",
                body,
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"Falha ao rodar 'gh issue create': {exc}") from exc
    if result.returncode != 0:
        raise GitError(f"Falha ao criar issue: {_redact_stderr(result.stderr)}")
    return result.stdout.strip()


def _current_branch(cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"Falha ao obter a branch atual: {exc}") from exc
    if result.returncode != 0:
        raise GitError(f"Falha ao obter a branch atual: {_redact_stderr(result.stderr)}")
    return result.stdout.strip()
