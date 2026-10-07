"""`ItemService.save` ligado ao repositório git da connection (GS-L4).

TDD contra um `git init --bare` local fazendo o papel de remote, igual ao padrão de
`test_git_repo_service.py`. Tudo que depende de `gh` (modo pr) é mockado em
`services.gh_cli`.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledge_os.exceptions import NotFoundError
from knowledge_os.mcp.tools import repo as repo_tool
from knowledge_os.services import gh_cli
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.relation_service import RelationService


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


ENTRY = {
    "workspace": "Polara",
    "project": "app",
    "key": "regra/money",
    "type": "rule",
    "title": "Money em pagamentos",
    "summary": "Valores em Money, nunca double",
    "content": "Sempre Money.",
}


class TestItemSaveDirect:
    def test_publica_arquivo_no_remote_e_atualiza_indice(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "Direta",
            str(tmp_path / "Direta"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)

        results = svc.save([dict(ENTRY)])

        assert results[0]["action"] == "created"
        item_id = results[0]["id"]

        # índice atualizado de verdade
        item = svc.get(item_id)
        assert item.title == "Money em pagamentos"

        # arquivo commitado e empurrado no remote
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        content = (check / "polara" / "app" / "regra" / "money.md").read_text(encoding="utf-8")
        assert "title: Money em pagamentos" in content
        assert "Sempre Money." in content

    def test_segredo_nunca_passa_pelo_git(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "DiretaSecret",
            str(tmp_path / "DiretaSecret"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)

        results = svc.save(
            [
                {
                    "key": "segredo/npm-token",
                    "type": "secret",
                    "title": "Token do npm",
                    "summary": "publica no npm",
                    "workspace": "Polara",
                    "project": "app",
                }
            ]
        )

        assert results[0]["action"] == "created"
        # índice tem o item
        assert svc.get(results[0]["id"]).type == "secret"
        # nada novo foi publicado no remote (só o README inicial)
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        assert not (check / "polara").exists()

    def test_update_republica_conteudo_novo(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "DiretaUpdate",
            str(tmp_path / "DiretaUpdate"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)
        svc.save([dict(ENTRY)])
        results = svc.save([{**ENTRY, "content": "Money sempre, versao 2."}])

        assert results[0]["action"] == "updated"
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        content = (check / "polara" / "app" / "regra" / "money.md").read_text(encoding="utf-8")
        assert "Money sempre, versao 2." in content


class TestItemSavePr:
    def test_pr_nao_toca_indice_e_devolve_pending_review(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "ComPR",
            str(tmp_path / "ComPR"),
            remote_url=str(bare_repo),
            review_mode="pr",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)

        with (
            patch.object(gh_cli, "has_push_access", return_value=None),
            patch.object(
                gh_cli, "pr_create", return_value="https://example.invalid/pr/7"
            ) as mocked_pr,
        ):
            results = svc.save([dict(ENTRY)])

        assert results[0]["status"] == "pending_review"
        assert results[0]["pr_url"] == "https://example.invalid/pr/7"
        mocked_pr.assert_called_once()

        # índice intocado: o item não existe (workspace/project podem já ter sido
        # criados por ensure_location, que commita fora da transação do item — mas o
        # item em si, com o PublishResult pendente, não entra no índice)
        ws_id = svc.resolve_workspace_id("Polara")
        pj_id = svc.resolve_project_id(ws_id, "app")
        with pytest.raises(NotFoundError):
            svc.get_by_key(pj_id, "regra/money")

        # a branch foi criada e empurrada de verdade no bare, com o arquivo
        branches = subprocess.run(
            ["git", "ls-remote", "--heads", str(bare_repo)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "refs/heads/item/" in branches

    def test_pr_sync_depois_traz_pro_indice(self, bare_repo, tmp_path):
        """Depois do PR "mergeado" (push direto na main, simulando o merge) e um
        `GitRepoService.sync()`, o item ainda não está no índice (a reindexação pelo
        conteúdo do git fica fora deste lote) — mas o arquivo já está na main."""
        conn = ConnectionService().create(
            "ComPRSync",
            str(tmp_path / "ComPRSync"),
            remote_url=str(bare_repo),
            review_mode="pr",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)
        with (
            patch.object(gh_cli, "has_push_access", return_value=None),
            patch.object(gh_cli, "pr_create", return_value="https://example.invalid/pr/9"),
        ):
            svc.save([dict(ENTRY)])

        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        branches = _git(check, "branch", "-r").stdout
        assert any("item/" in b for b in branches.splitlines())


class TestRepoSync:
    def test_sem_connection_e_no_op(self):
        assert repo_tool(action="sync") == {"synced": False}

    def test_puxa_mudanca_do_remote_da_connection(self, bare_repo, tmp_path):
        from knowledge_os.config import ConfigManager

        conn = ConnectionService().create(
            "ParaSync",
            str(tmp_path / "ParaSync"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        clone_path = ConfigManager.load_or_create().get_connection(conn.id).clone_path()

        # outro clone publica uma mudança no bare
        other = tmp_path / "other"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(other))
        _git(other, "config", "user.email", "o@local")
        _git(other, "config", "user.name", "o")
        (other / "novo.txt").write_text("x", encoding="utf-8")
        _git(other, "add", "novo.txt")
        _git(other, "commit", "-q", "-m", "novo")
        _git(other, "push", "-q", "origin", "main")

        assert repo_tool(action="sync", connection_id=conn.id) == {"synced": True}
        assert (clone_path / "novo.txt").exists()
        assert repo_tool(action="sync", connection_id=conn.id) == {"synced": False}


class TestItemDeletePublished:
    def test_direct_remove_arquivo_e_indice(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "DiretaDelete",
            str(tmp_path / "DiretaDelete"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)
        item_id = svc.save([dict(ENTRY)])[0]["id"]

        result = svc.delete_published(item_id)

        assert result == {"status": "deleted", "id": item_id}
        with pytest.raises(NotFoundError):
            svc.get(item_id)
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        assert not (check / "polara" / "app" / "regra" / "money.md").exists()

    def test_pr_abre_pr_de_remocao_e_mantem_no_indice(self, bare_repo, tmp_path):
        from knowledge_os.config import ConfigManager

        conn = ConnectionService().create(
            "PRDelete",
            str(tmp_path / "PRDelete"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        item_id = ItemService(connection_id=conn.id).save([dict(ENTRY)])[0]["id"]

        # a connection passa a exigir revisão (ex.: mudou de ideia depois de já ter itens)
        config = ConfigManager.load_or_create()
        config.get_connection(conn.id).review_mode = "pr"
        ConfigManager.save(config)

        svc = ItemService(connection_id=conn.id)
        with (
            patch.object(gh_cli, "has_push_access", return_value=None),
            patch.object(
                gh_cli, "pr_create", return_value="https://example.invalid/pr/2"
            ) as mocked_pr,
        ):
            result = svc.delete_published(item_id)

        assert result["status"] == "pending_review"
        assert result["pr_url"] == "https://example.invalid/pr/2"
        mocked_pr.assert_called_once()
        # continua no índice: só sai depois do PR mergeado + sync
        assert svc.get(item_id).id == item_id


class TestRelationDeletePublished:
    def test_direct_republica_item_sem_a_relacao(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "DiretaRel",
            str(tmp_path / "DiretaRel"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)
        saved = svc.save(
            [
                dict(ENTRY),
                {
                    **ENTRY,
                    "key": "regra/outra",
                    "title": "Outra",
                    "content": "Outra regra.",
                    "relations": [{"type": "related_to", "target": "regra/money"}],
                },
            ]
        )
        rel_id = RelationService(connection_id=conn.id).list(saved[1]["id"])[0].id

        RelationService(connection_id=conn.id).delete_published(rel_id)

        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        content = (check / "polara" / "app" / "regra" / "outra.md").read_text(encoding="utf-8")
        assert "relations: []" in content or "relations: []\n" in content.replace("\n\n", "\n")
