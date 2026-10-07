"""Clona/puxa/publica num repositório git local (com ou sem remote GitHub).

Dois modos de curadoria por connection (`review_mode`):
- `direct`: escreve, comita e empurra direto na branch principal do clone.
- `pr`: escreve numa branch nova, empurra e abre PR (ou Issue, se não houver
  permissão de push no remote).

Só este módulo e `gh_cli.py` chamam `git`/`gh`: sempre via lista de argumentos em
`subprocess.run(cwd=..., capture_output=True, text=True)`, nunca `shell=True` nem
interpolação de string em comando.
"""

import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from knowledge_os.exceptions import GitError
from knowledge_os.services import gh_cli

_PUSH_RETRY_BUDGET_S = 10.0
_PUSH_RETRY_FIRST_WAIT_S = 0.05
_PUSH_RETRY_MAX_WAIT_S = 1.0

_NON_FAST_FORWARD_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "updates were rejected",
    "incorrect old value",
    "stale info",
)

_MANAGED_WORKFLOW_MARKER = "# gerado por knowledge-os, não editar abaixo desta linha"
_MANAGED_CODEOWNERS_MARKER = "# gerado por knowledge-os, não editar abaixo desta linha"

_WORKFLOW_PATH = ".github/workflows/validate-items.yml"
_VALIDATE_SCRIPT_PATH = ".github/scripts/validate_items.py"
_CODEOWNERS_PATH = "CODEOWNERS"

_VALIDATE_SCRIPT_CONTENT = '''"""Valida os itens alterados num PR: sem segredo, sem key duplicada.

Rodado pelo workflow `validate-items.yml` sobre os arquivos do diff do PR.
"""

import re
import sys
from pathlib import Path

from knowledge_os.services.secret_guard import ensure_no_secrets

_KEY_RE = re.compile(r"^key:\\s*(.+)$", re.MULTILINE)


def _key_of(path: Path) -> str | None:
    match = _KEY_RE.search(path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else None


def main(paths: list[str]) -> int:
    seen: dict[str, str] = {}
    for raw in paths:
        path = Path(raw)
        if not path.exists() or path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        try:
            ensure_no_secrets(content=text)
        except Exception as exc:  # noqa: BLE001 - mensagem clara pro CI
            print(f"{path}: {exc}")
            return 1
        key = _key_of(path)
        if key is None:
            continue
        if key in seen:
            print(f"key duplicada {key!r}: {seen[key]} e {path}")
            return 1
        seen[key] = str(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

_WORKFLOW_CONTENT = f"""{_MANAGED_WORKFLOW_MARKER}
name: validate-items

on:
  pull_request:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lista arquivos alterados
        id: diff
        run: |
          git fetch origin ${{{{ github.base_ref }}}} --depth=1
          changed=$(git diff --name-only origin/${{{{ github.base_ref }}}} HEAD | tr '\\n' ' ')
          echo "files=$changed" >> "$GITHUB_OUTPUT"
      - name: Valida itens (sem segredo, sem key duplicada)
        run: python {_VALIDATE_SCRIPT_PATH} ${{{{ steps.diff.outputs.files }}}}
"""


@dataclass(frozen=True)
class PublishResult:
    """Resultado de `GitRepoService.publish`.

    `status`: "published" (direct), "pending_review" (pr com PR aberto) ou
    "issue_opened" (pr sem permissão de push, caiu pra Issue).
    """

    status: Literal["published", "pending_review", "issue_opened"]
    commit_sha: str | None = None
    pr_url: str | None = None
    issue_url: str | None = None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "update"


class GitRepoService:
    """Por connection: `clone_path`, `remote_url` (None = repositório local sem GitHub)."""

    def __init__(
        self,
        clone_path: Path,
        remote_url: str | None = None,
        review_mode: Literal["direct", "pr"] = "direct",
    ) -> None:
        self.clone_path = Path(clone_path)
        self.remote_url = remote_url
        self.review_mode = review_mode

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args], cwd=self.clone_path, capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitError(f"Falha ao rodar 'git {' '.join(args)}': {exc}") from exc
        if check and result.returncode != 0:
            raise GitError(f"Falha em 'git {' '.join(args)}': {result.stderr.strip()}")
        return result

    def _run_in(
        self, cwd: Path, args: list[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitError(f"Falha ao rodar 'git {' '.join(args)}': {exc}") from exc
        if check and result.returncode != 0:
            raise GitError(f"Falha em 'git {' '.join(args)}': {result.stderr.strip()}")
        return result

    def _main_branch(self) -> str:
        """Nome da branch atual — funciona mesmo sem nenhum commit ainda (HEAD órfã)."""
        result = self._run(["symbolic-ref", "--short", "HEAD"])
        return result.stdout.strip()

    def _has_remote(self) -> bool:
        if self.remote_url is None:
            return False
        result = self._run(["remote"], check=False)
        return "origin" in result.stdout.split()

    def is_git_repo(self) -> bool:
        """True se `clone_path` já é a raiz de um repositório git."""
        if not self.clone_path.is_dir():
            return False
        result = self._run(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def ensure_clone(self) -> Path:
        """Clona na primeira vez; sem `remote_url`, `git init` local (preserva arquivos já
        existentes na pasta). Idempotente — se já é um repositório git, não mexe.
        """
        if self.clone_path.exists() and self.is_git_repo():
            return self.clone_path
        self.clone_path.mkdir(parents=True, exist_ok=True)
        if self.remote_url is not None:
            try:
                result = subprocess.run(
                    ["git", "clone", self.remote_url, str(self.clone_path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise GitError(f"Falha ao clonar {self.remote_url!r}: {exc}") from exc
            if result.returncode != 0:
                raise GitError(f"Falha ao clonar {self.remote_url!r}: {result.stderr.strip()}")
        else:
            self._run(["init"])
        self._run(["config", "user.email", "knowledge-os@local"], check=False)
        self._run(["config", "user.name", "knowledge-os"], check=False)
        return self.clone_path

    def pull(self) -> None:
        """`git pull` na branch principal; no-op se não há remote configurado."""
        if not self._has_remote():
            return
        self._run(["pull", "--ff-only", "origin", self._main_branch()])

    def sync(self) -> bool:
        """Compara `ls-remote` (sem baixar objetos) com o HEAD local; puxa se diferente."""
        if not self._has_remote():
            return False
        branch = self._main_branch()
        remote_sha = self._ls_remote_sha(branch)
        local_sha = self._run(["rev-parse", "HEAD"]).stdout.strip()
        if remote_sha is None or remote_sha == local_sha:
            return False
        self.pull()
        return True

    def _ls_remote_sha(self, branch: str) -> str | None:
        assert self.remote_url is not None
        result = self._run(["ls-remote", self.remote_url, branch], check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return result.stdout.split()[0]

    def _write_files(self, files: dict[str, str | None]) -> None:
        for rel_path, content in files.items():
            full = self.clone_path / rel_path
            if content is None:
                if full.exists():
                    self._run(["rm", "-f", rel_path])
                continue
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            self._run(["add", rel_path])

    def _commit(self, message: str) -> str | None:
        status = self._run(["status", "--porcelain"]).stdout
        if not status.strip():
            return self._run(["rev-parse", "HEAD"], check=False).stdout.strip() or None
        self._run(["commit", "-m", message])
        return self._run(["rev-parse", "HEAD"]).stdout.strip()

    def _push_with_retry(self, branch: str, rewrite: Callable[[], str | None]) -> str | None:
        """Tenta publicar `branch`; em rejeição (non-fast-forward), descarta o commit local
        (`reset --hard` pro que o remote tem agora) e chama `rewrite()` de novo.

        Não usa `rebase`: como o publisher só escreve um conjunto conhecido de arquivos (não
        faz merge de texto de verdade), reescrever por cima do estado novo do remote é seguro
        e, ao contrário do rebase, nunca entra em conflito — um conflito de merge deixaria o
        clone parado em "rebasing", quebrando qualquer publish seguinte na mesma connection.
        """
        sha = rewrite()
        deadline = time.monotonic() + _PUSH_RETRY_BUDGET_S
        wait = _PUSH_RETRY_FIRST_WAIT_S
        last_error: GitError | None = None
        while True:
            result = self._run(["push", "origin", branch], check=False)
            if result.returncode == 0:
                return sha
            stderr_lower = result.stderr.lower()
            if not any(marker in stderr_lower for marker in _NON_FAST_FORWARD_MARKERS):
                raise GitError(f"Falha em 'git push': {result.stderr.strip()}")
            last_error = GitError(f"Falha em 'git push' (rejeitado): {result.stderr.strip()}")
            if time.monotonic() + wait > deadline:
                raise last_error
            time.sleep(wait)
            wait = min(wait * 2, _PUSH_RETRY_MAX_WAIT_S)
            self._run(["fetch", "origin", branch])
            self._run(["reset", "--hard", f"origin/{branch}"])
            sha = rewrite()

    def publish(
        self,
        files: dict[str, str | None],
        message: str,
        branch_hint: str | None = None,
    ) -> PublishResult:
        """Escreve/remove `files` ({path: conteúdo, None = remover}) e publica.

        `direct`: commit + push na branch principal (com retry em rejeição de push
        concorrente). `pr`: branch nova + commit + push + PR (ou Issue, se não há
        permissão de push).
        """
        if self.review_mode == "direct":
            return self._publish_direct(files, message)
        return self._publish_pr(files, message, branch_hint)

    def _publish_direct(self, files: dict[str, str | None], message: str) -> PublishResult:
        branch = self._main_branch()

        def rewrite() -> str | None:
            self._write_files(files)
            return self._commit(message)

        if self._has_remote():
            sha = self._push_with_retry(branch, rewrite)
        else:
            sha = rewrite()
        return PublishResult(status="published", commit_sha=sha)

    def _publish_pr(
        self, files: dict[str, str | None], message: str, branch_hint: str | None
    ) -> PublishResult:
        base_branch = self._main_branch()
        branch = f"item/{_slugify(branch_hint or message)}"
        self._run(["checkout", "-b", branch], check=False)
        self._run(["checkout", branch])

        owner_repo = self._owner_repo()
        access = gh_cli.has_push_access(owner_repo) if owner_repo else None
        if access is False:
            self._run(["checkout", base_branch])
            issue_url = gh_cli.issue_create(owner_repo, message, self._issue_body(files, message))
            return PublishResult(status="issue_opened", issue_url=issue_url)

        def rewrite() -> str | None:
            self._write_files(files)
            return self._commit(message)

        self._push_with_retry(branch, rewrite)
        pr_url = gh_cli.pr_create(
            self.clone_path, message, self._issue_body(files, message), base=base_branch
        )
        return PublishResult(status="pending_review", pr_url=pr_url)

    @staticmethod
    def _issue_body(files: dict[str, str | None], message: str) -> str:
        lines = [message, "", "Arquivos propostos:"]
        for path, content in files.items():
            action = "remover" if content is None else "escrever"
            lines.append(f"- {action}: {path}")
        return "\n".join(lines)

    def _owner_repo(self) -> str | None:
        if self.remote_url is None:
            return None
        match = re.search(r"github\.com[:/](?P<owner_repo>[^/]+/[^/.]+)", self.remote_url)
        if match is None:
            return None
        return match.group("owner_repo").removesuffix(".git")

    def ensure_workflow(self) -> bool:
        """Escreve `.github/workflows/validate-items.yml` + script auxiliar (idempotente).

        A key única é checada por um script Python simples (`validate_items.py`
        escrito junto): grep de `^key:` nos `.md` do diff, erro se duas keys batem.
        Roda `ensure_no_secrets` sobre o conteúdo de cada arquivo também.
        """
        changed = False
        changed |= self._write_if_changed(_VALIDATE_SCRIPT_PATH, _VALIDATE_SCRIPT_CONTENT)
        changed |= self._write_if_changed(_WORKFLOW_PATH, _WORKFLOW_CONTENT)
        return changed

    def _write_if_changed(self, rel_path: str, content: str) -> bool:
        full = self.clone_path / rel_path
        if full.exists() and full.read_text(encoding="utf-8") == content:
            return False
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return True

    def ensure_codeowners(self, rules: list[tuple[str, str]]) -> bool:
        """Atualiza o bloco gerenciado de `CODEOWNERS` a partir de `[(path_pattern, owner), ...]`.

        Preserva linhas fora do bloco gerenciado (comentário humano, regra manual):
        só reescreve o que está abaixo do marcador `_MANAGED_CODEOWNERS_MARKER`.
        """
        full = self.clone_path / _CODEOWNERS_PATH
        managed_lines = [f"{pattern} {owner}" for pattern, owner in rules]
        managed_block = "\n".join([_MANAGED_CODEOWNERS_MARKER, *managed_lines, ""])

        if not full.exists():
            full.write_text(managed_block, encoding="utf-8")
            return True

        existing = full.read_text(encoding="utf-8")
        if _MANAGED_CODEOWNERS_MARKER in existing:
            prefix = existing.split(_MANAGED_CODEOWNERS_MARKER, 1)[0]
        else:
            prefix = existing if existing.endswith("\n") or not existing else existing + "\n"
        new_content = prefix + managed_block
        if new_content == existing:
            return False
        full.write_text(new_content, encoding="utf-8")
        return True
