"""GitRepoService: TDD contra um `git init --bare` local fazendo o papel de remote.

Tudo que depende de `gh` (modo pr, has_push_access, pr_create, issue_create) é mockado
em `services.gh_cli` — é a única borda de rede, não precisa de GitHub de verdade.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledge_os.services import gh_cli
from knowledge_os.services.git_repo_service import GitRepoService

ROOT = Path(__file__).resolve().parent.parent


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def bare_repo(tmp_path):
    """Bare repo local com um commit inicial na branch `main` — faz o papel de remote."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "_seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True)
    _git(seed, "config", "user.email", "seed@local")
    _git(seed, "config", "user.name", "seed")
    (seed / "README.md").write_text("inicial\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-q", "-m", "inicial")
    _git(seed, "push", "-q", "origin", "main")
    return bare


def _clone_path(tmp_path, name="clone"):
    return tmp_path / name


class TestEnsureClone:
    def test_clona_de_remote_real(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo))
        result = svc.ensure_clone()
        assert result == clone_path
        assert (clone_path / "README.md").exists()
        assert (clone_path / ".git").is_dir()

    def test_idempotente_sem_remote_ja_clonado(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo))
        svc.ensure_clone()
        svc.ensure_clone()  # não falha

    def test_sem_remote_faz_init_local(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        assert (clone_path / ".git").is_dir()

    def test_init_local_idempotente(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        svc.ensure_clone()  # não falha


class TestPull:
    def test_no_op_sem_remote(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        svc.pull()  # não levanta

    def test_puxa_mudanca_do_remote(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo))
        svc.ensure_clone()

        # outro clone publica uma mudança no bare
        other = tmp_path / "other"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(other))
        _git(other, "config", "user.email", "o@local")
        _git(other, "config", "user.name", "o")
        (other / "novo.txt").write_text("x", encoding="utf-8")
        _git(other, "add", "novo.txt")
        _git(other, "commit", "-q", "-m", "novo")
        _git(other, "push", "-q", "origin", "main")

        assert not (clone_path / "novo.txt").exists()
        svc.pull()
        assert (clone_path / "novo.txt").exists()


class TestPublishDirect:
    def test_commit_e_push_reais(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo), review_mode="direct")
        svc.ensure_clone()

        result = svc.publish({"item.md": "conteudo"}, "adiciona item")

        assert result.status == "published"
        assert result.commit_sha

        # confere no bare via outro clone
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        assert (check / "item.md").read_text(encoding="utf-8") == "conteudo"

    def test_remove_arquivo(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo), review_mode="direct")
        svc.ensure_clone()
        svc.publish({"item.md": "conteudo"}, "adiciona item")
        svc.publish({"item.md": None}, "remove item")

        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        assert not (check / "item.md").exists()

    def test_sem_remote_so_commita(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None, review_mode="direct")
        svc.ensure_clone()
        result = svc.publish({"item.md": "conteudo"}, "adiciona item")
        assert result.status == "published"
        assert (clone_path / "item.md").read_text(encoding="utf-8") == "conteudo"


class TestPublishPr:
    def test_cria_branch_e_pr(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo), review_mode="pr")
        svc.ensure_clone()

        with (
            patch.object(gh_cli, "has_push_access", return_value=None),
            patch.object(
                gh_cli, "pr_create", return_value="https://example.invalid/pr/1"
            ) as mocked_pr,
        ):
            result = svc.publish({"item.md": "conteudo"}, "adiciona item", branch_hint="item-x")

        assert result.status == "pending_review"
        assert result.pr_url == "https://example.invalid/pr/1"
        mocked_pr.assert_called_once()

        # a branch foi criada e empurrada de verdade no bare
        branches = subprocess.run(
            ["git", "branch", "-r"], cwd=clone_path, capture_output=True, text=True, check=True
        ).stdout
        assert "origin/item/item-x" in branches

    def test_volta_para_a_branch_principal_depois_do_pr(self, tmp_path, bare_repo):
        """A pasta é a fonte de leitura: o que está em revisão não aparece nela até o merge."""
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo), review_mode="pr")
        svc.ensure_clone()

        with (
            patch.object(gh_cli, "has_push_access", return_value=None),
            patch.object(gh_cli, "pr_create", return_value="https://example.invalid/pr/1"),
        ):
            svc.publish({"item.md": "conteudo"}, "adiciona item", branch_hint="item-y")

        head = _git(clone_path, "symbolic-ref", "--short", "HEAD").stdout.strip()
        assert head == "main"
        assert not (clone_path / "item.md").exists()


class TestWriteFiles:
    def test_grava_com_lf_e_remove_arquivo_e_pasta_vazia(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path)
        svc.ensure_clone()
        svc.publish({"a/b/item.md": "linha 1\nlinha 2\n"}, "cria")
        assert (clone_path / "a" / "b" / "item.md").read_bytes() == b"linha 1\nlinha 2\n"

        svc.publish({"a/b/item.md": None, "nunca-existiu.md": None}, "remove")
        assert not (clone_path / "a").exists()
        tracked = _git(clone_path, "ls-files").stdout
        assert "item.md" not in tracked


class TestPublishPrIssue:
    def test_sem_permissao_de_push_abre_issue(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        # remote_url "github" só para o parse de owner/repo; o git real aponta pro bare local.
        svc = GitRepoService(
            clone_path=clone_path,
            remote_url="git@github.com:org/repo.git",
            review_mode="pr",
        )
        clone_path.mkdir()
        _git(clone_path, "init", "-q", "-b", "main")
        _git(clone_path, "config", "user.email", "x@local")
        _git(clone_path, "config", "user.name", "x")
        (clone_path / "README.md").write_text("inicial\n", encoding="utf-8")
        _git(clone_path, "add", "README.md")
        _git(clone_path, "commit", "-q", "-m", "inicial")
        _git(clone_path, "remote", "add", "origin", str(bare_repo))

        with (
            patch.object(gh_cli, "has_push_access", return_value=False),
            patch.object(
                gh_cli, "issue_create", return_value="https://example.invalid/issues/2"
            ) as mocked_issue,
        ):
            result = svc.publish({"item.md": "conteudo"}, "adiciona item")

        assert result.status == "issue_opened"
        assert result.issue_url == "https://example.invalid/issues/2"
        mocked_issue.assert_called_once()
        owner_repo_arg = mocked_issue.call_args.args[0]
        assert owner_repo_arg == "org/repo"


class TestSync:
    def test_sem_remote_no_op(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        assert svc.sync() is False

    def test_puxa_so_quando_necessario(self, tmp_path, bare_repo):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=str(bare_repo))
        svc.ensure_clone()

        assert svc.sync() is False  # já está igual ao remote

        other = tmp_path / "other"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(other))
        _git(other, "config", "user.email", "o@local")
        _git(other, "config", "user.name", "o")
        (other / "novo.txt").write_text("x", encoding="utf-8")
        _git(other, "add", "novo.txt")
        _git(other, "commit", "-q", "-m", "novo")
        _git(other, "push", "-q", "origin", "main")

        assert svc.sync() is True
        assert (clone_path / "novo.txt").exists()
        assert svc.sync() is False  # já sincronizado agora


class TestEnsureWorkflow:
    def test_escreve_na_primeira_vez(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        assert svc.ensure_workflow() is True
        assert (clone_path / ".github/workflows/validate-items.yml").exists()
        assert (clone_path / ".github/scripts/validate_items.py").exists()

    def test_idempotente(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        svc.ensure_workflow()
        assert svc.ensure_workflow() is False


class TestEnsureCodeowners:
    def test_escreve_na_primeira_vez(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        assert svc.ensure_codeowners([("polara/*", "@fulano")]) is True
        content = (clone_path / "CODEOWNERS").read_text(encoding="utf-8")
        assert "polara/* @fulano" in content

    def test_idempotente(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        svc.ensure_codeowners([("polara/*", "@fulano")])
        assert svc.ensure_codeowners([("polara/*", "@fulano")]) is False

    def test_preserva_linhas_humanas(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        (clone_path / "CODEOWNERS").write_text(
            "# regra manual do time\nfoo/* @manual\n", encoding="utf-8"
        )
        svc.ensure_codeowners([("polara/*", "@fulano")])
        content = (clone_path / "CODEOWNERS").read_text(encoding="utf-8")
        assert "# regra manual do time" in content
        assert "foo/* @manual" in content
        assert "polara/* @fulano" in content

    def test_atualiza_regra_gerenciada_sem_duplicar(self, tmp_path):
        clone_path = _clone_path(tmp_path)
        svc = GitRepoService(clone_path=clone_path, remote_url=None)
        svc.ensure_clone()
        svc.ensure_codeowners([("polara/*", "@fulano")])
        svc.ensure_codeowners([("polara/*", "@ciclano")])
        content = (clone_path / "CODEOWNERS").read_text(encoding="utf-8")
        assert content.count("polara/*") == 1
        assert "@ciclano" in content
        assert "@fulano" not in content


# --- concorrência real: dois processos publicando (modo direct) no mesmo bare ---

_WORKER = (
    "import sys\n"
    "from pathlib import Path\n"
    "from knowledge_os.services.git_repo_service import GitRepoService\n"
    "clone_path = Path(sys.argv[1])\n"
    "bare = sys.argv[2]\n"
    "n = sys.argv[3]\n"
    "svc = GitRepoService(clone_path=clone_path, remote_url=bare, review_mode='direct')\n"
    "result = svc.publish({f'from_{n}.txt': f'content {n}'}, f'msg {n}')\n"
    "print(result.status, result.commit_sha)\n"
)


def _env():
    return {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def test_push_rejeitado_no_mesmo_arquivo_nao_trava_o_clone_em_rebase(tmp_path, bare_repo):
    """Dois publishes concorrentes no MESMO arquivo (conteúdo diferente): o antigo código
    fazia `rebase` depois do fetch, que entra em conflito de merge de verdade (mesma linha)
    e deixa o clone parado em "rebasing", quebrando qualquer publish seguinte — mesmo de um
    arquivo totalmente diferente. O retry precisa resolver sem merge de texto: descarta o que
    está pendente localmente e reescreve o arquivo por cima do que o remote tem agora.
    """
    a = GitRepoService(clone_path=tmp_path / "a", remote_url=str(bare_repo), review_mode="direct")
    a.ensure_clone()
    b = GitRepoService(clone_path=tmp_path / "b", remote_url=str(bare_repo), review_mode="direct")
    b.ensure_clone()

    # A publica primeiro e vence a corrida.
    result_a = a.publish({"item.md": "versao de A"}, "A escreve item.md")
    assert result_a.status == "published"

    # B ainda está no commit anterior: seu push é rejeitado (non-fast-forward) e o retry
    # precisa lidar com o MESMO path mudado nos dois lados, sem travar o clone.
    result_b = b.publish({"item.md": "versao de B"}, "B escreve item.md")
    assert result_b.status == "published"

    # O clone de B não pode ficar preso num rebase pendente: um publish seguinte, de um
    # arquivo totalmente diferente, tem que funcionar normalmente.
    result_b2 = b.publish({"outro.md": "outro conteudo"}, "B escreve outro.md")
    assert result_b2.status == "published"

    check = tmp_path / "check"
    _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
    assert (check / "item.md").read_text(encoding="utf-8") == "versao de B"
    assert (check / "outro.md").read_text(encoding="utf-8") == "outro conteudo"


def test_dois_processos_publicam_push_concorrente_com_retry(tmp_path, bare_repo):
    """Dois processos reais, pré-clonados do mesmo commit, publicam ao mesmo tempo.

    Um dos dois leva rejeição de push (non-fast-forward) e precisa do retry
    (fetch + rebase + nova tentativa) para completar com sucesso.
    """
    dir1, dir2 = tmp_path / "w1", tmp_path / "w2"
    for d in (dir1, dir2):
        svc = GitRepoService(clone_path=d, remote_url=str(bare_repo), review_mode="direct")
        svc.ensure_clone()

    env = _env()
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(d), str(bare_repo), str(n)],
            env=env,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n, d in enumerate((dir1, dir2))
    ]
    outs = [p.communicate(timeout=60) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs

    check = tmp_path / "check"
    _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
    assert (check / "from_0.txt").exists()
    assert (check / "from_1.txt").exists()
