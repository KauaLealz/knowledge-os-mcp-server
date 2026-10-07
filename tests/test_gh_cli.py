"""gh_cli: cada função é um subprocess `gh`/`git` + parse — subprocess.run mockado."""

import subprocess
from unittest.mock import patch

import pytest

from knowledge_os.exceptions import GitError
from knowledge_os.services import gh_cli


def _result(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestIsAuthenticated:
    def test_exit_zero_autenticado(self):
        with patch("subprocess.run", return_value=_result(returncode=0)) as mocked:
            assert gh_cli.is_authenticated() is True
        assert mocked.call_args.args[0][:2] == ["gh", "auth"]

    def test_exit_diferente_de_zero_nao_autenticado(self):
        with patch("subprocess.run", return_value=_result(returncode=1, stderr="not logged in")):
            assert gh_cli.is_authenticated() is False

    def test_gh_nao_instalado(self):
        with patch("subprocess.run", side_effect=OSError("no such file")):
            assert gh_cli.is_authenticated() is False


class TestHasPushAccess:
    def test_true(self):
        with patch("subprocess.run", return_value=_result(stdout="true\n")):
            assert gh_cli.has_push_access("org/repo") is True

    def test_false(self):
        with patch("subprocess.run", return_value=_result(stdout="false\n")):
            assert gh_cli.has_push_access("org/repo") is False

    def test_falha_devolve_none(self):
        with patch("subprocess.run", return_value=_result(returncode=1, stderr="HTTP 404")):
            assert gh_cli.has_push_access("org/repo") is None

    def test_saida_omissa_devolve_none(self):
        with patch("subprocess.run", return_value=_result(stdout="")):
            assert gh_cli.has_push_access("org/repo") is None

    def test_excecao_devolve_none(self):
        with patch("subprocess.run", side_effect=OSError("no such file")):
            assert gh_cli.has_push_access("org/repo") is None


class TestPrCreate:
    def test_caminho_feliz(self, tmp_path):
        branch_result = _result(stdout="feat/x\n")
        pr_result = _result(stdout="https://github.com/org/repo/pull/1\n")
        with patch("subprocess.run", side_effect=[branch_result, pr_result]) as mocked:
            url = gh_cli.pr_create(tmp_path, "titulo", "corpo", base="main")
        assert url == "https://github.com/org/repo/pull/1"
        pr_call = mocked.call_args_list[1].args[0]
        assert pr_call[:3] == ["gh", "pr", "create"]
        assert "--head" in pr_call and "feat/x" in pr_call
        assert "--base" in pr_call and "main" in pr_call

    def test_erro_levanta_giterror(self, tmp_path):
        branch_result = _result(stdout="feat/x\n")
        pr_result = _result(returncode=1, stderr="pull request create failed")
        with patch("subprocess.run", side_effect=[branch_result, pr_result]):
            with pytest.raises(GitError, match="Falha ao criar PR"):
                gh_cli.pr_create(tmp_path, "titulo", "corpo")

    def test_stderr_com_token_e_redigido(self, tmp_path):
        branch_result = _result(stdout="feat/x\n")
        token = "ghp_" + "a" * 36
        pr_result = _result(returncode=1, stderr=f"auth failed with token {token}")
        with patch("subprocess.run", side_effect=[branch_result, pr_result]):
            with pytest.raises(GitError) as exc_info:
                gh_cli.pr_create(tmp_path, "titulo", "corpo")
        assert token not in str(exc_info.value)
        assert "token do GitHub" in str(exc_info.value)


class TestIssueCreate:
    def test_caminho_feliz(self):
        with patch(
            "subprocess.run",
            return_value=_result(stdout="https://github.com/org/repo/issues/2\n"),
        ) as mocked:
            url = gh_cli.issue_create("org/repo", "titulo", "corpo")
        assert url == "https://github.com/org/repo/issues/2"
        call = mocked.call_args.args[0]
        assert call[:3] == ["gh", "issue", "create"]
        assert "--repo" in call and "org/repo" in call

    def test_erro_levanta_giterror(self):
        with patch("subprocess.run", return_value=_result(returncode=1, stderr="boom")):
            with pytest.raises(GitError, match="Falha ao criar issue"):
                gh_cli.issue_create("org/repo", "titulo", "corpo")
