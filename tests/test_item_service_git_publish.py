"""`ItemService.save` publicando no repositório git da connection (GS-L4).

TDD contra um `git init --bare` local fazendo o papel de remote, igual ao padrão de
`test_git_repo_service.py`. Tudo que depende de `gh` (modo pr) é mockado em
`services.gh_cli`.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledge_os.exceptions import NotFoundError
from knowledge_os.services import gh_cli
from knowledge_os.services.connection_service import ConnectionService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.relation_service import RelationService


def repo_tool(**kwargs):
    """Ferramenta MCP `repo` (importada aqui: o MCP é da fase 6)."""
    from knowledge_os.mcp.tools import repo

    return repo(**kwargs)


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
    def test_publica_arquivo_no_remote_e_le_da_pasta(self, bare_repo, tmp_path):
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

        # a leitura seguinte já vê o arquivo
        item = svc.get(item_id)
        assert item.title == "Money em pagamentos"

        # arquivo commitado e empurrado no remote
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        content = (check / "polara" / "app" / "regra" / "money.md").read_text(encoding="utf-8")
        assert "title: Money em pagamentos" in content
        assert "Sempre Money." in content

    def test_segredo_vai_ao_git_so_com_metadados(self, bare_repo, tmp_path):
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
        assert svc.get(results[0]["id"]).type == "secret"
        # o item vai ao remote como os outros, só com título e resumo
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        text = (check / "polara" / "app" / "segredo" / "npm-token.md").read_text(encoding="utf-8")
        assert "type: secret" in text and "publica no npm" in text

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
    def test_pr_nao_muda_a_pasta_e_devolve_pending_review(self, bare_repo, tmp_path):
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

        # a pasta continua na branch principal: o item só aparece depois do merge + sync
        with pytest.raises(NotFoundError):
            svc.get_by_key("polara", "app", "regra/money")
        assert svc.search(everywhere=True, status=["active", "archived", "review"])["results"] == []

        # a branch foi criada e empurrada de verdade no bare, com o arquivo
        branches = subprocess.run(
            ["git", "ls-remote", "--heads", str(bare_repo)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "refs/heads/item/" in branches

    def test_pr_empurra_a_branch_do_item(self, bare_repo, tmp_path):
        """A branch do PR chega ao remote (o merge em si é do GitHub)."""
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
    def test_sem_connection_da_erro_claro(self):
        from knowledge_os.exceptions import NoConnectionError

        with pytest.raises(NoConnectionError, match="connection_create"):
            repo_tool(action="sync")

    def test_connection_sem_remote_e_no_op(self, tmp_path):
        ConnectionService().create("Local", str(tmp_path / "Local"), test=False)
        assert repo_tool(action="sync") == {"synced": False}

    def test_sync_traz_o_item_mergeado_para_a_leitura(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "Leitura", str(tmp_path / "Leitura"), remote_url=str(bare_repo), test=False
        )
        other = tmp_path / "other"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(other))
        _git(other, "config", "user.email", "o@local")
        _git(other, "config", "user.name", "o")
        (other / "polara" / "app").mkdir(parents=True)
        (other / "polara" / "app" / "x.md").write_text(
            "---\nkey: x\nid: id-x\nworkspace: Polara\nproject: app\ntype: rule\n"
            "title: Vindo do merge\nstatus: active\nmemory_class: longterm\n"
            "created_at: '2026-01-01T00:00:00Z'\nupdated_at: '2026-01-01T00:00:00Z'\n"
            "summary: s\n---\ncorpo\n",
            encoding="utf-8",
        )
        _git(other, "add", ".")
        _git(other, "commit", "-q", "-m", "merge")
        _git(other, "push", "-q", "origin", "main")

        assert repo_tool(action="sync", connection_id=conn.id) == {"synced": True}
        found = ItemService(connection_id=conn.id).search("merge", everywhere=True)
        assert [r["id"] for r in found["results"]] == ["id-x"]

    def test_puxa_mudanca_do_remote_da_connection(self, bare_repo, tmp_path):
        from knowledge_os.config import ConfigManager

        conn = ConnectionService().create(
            "ParaSync",
            str(tmp_path / "ParaSync"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        clone_path = ConfigManager.load().get_connection(conn.id).clone_path()

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
    def test_direct_remove_o_arquivo(self, bare_repo, tmp_path):
        conn = ConnectionService().create(
            "DiretaDelete",
            str(tmp_path / "DiretaDelete"),
            remote_url=str(bare_repo),
            review_mode="direct",
            test=False,
        )
        svc = ItemService(connection_id=conn.id)
        item_id = svc.save([dict(ENTRY)])[0]["id"]

        result = svc.delete(ids=[item_id], confirm=True)

        assert result == {"status": "deleted", "ids": [item_id]}
        with pytest.raises(NotFoundError):
            svc.get(item_id)
        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        assert not (check / "polara" / "app" / "regra" / "money.md").exists()

    def test_pr_abre_pr_de_remocao_e_mantem_na_pasta(self, bare_repo, tmp_path):
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
        config = ConfigManager.load()
        config.get_connection(conn.id).review_mode = "pr"
        ConfigManager.save(config)

        svc = ItemService(connection_id=conn.id)
        with (
            patch.object(gh_cli, "has_push_access", return_value=None),
            patch.object(
                gh_cli, "pr_create", return_value="https://example.invalid/pr/2"
            ) as mocked_pr,
        ):
            result = svc.delete(ids=[item_id], confirm=True)

        assert result["status"] == "pending_review" and result["ids"] == [item_id]
        assert result["pr_url"] == "https://example.invalid/pr/2"
        mocked_pr.assert_called_once()
        # continua na pasta: só sai depois do PR mergeado + sync
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
        svc.save([dict(ENTRY), {**ENTRY, "key": "regra/outra", "title": "Outra",
                                "content": "Outra regra."}])
        rel = [{"source": "regra/outra", "type": "related_to", "target": "regra/money"}]
        relations = RelationService(connection_id=conn.id)
        relations.create(rel, viewpoint=("polara", "app"))

        assert relations.delete(rel, viewpoint=("polara", "app"))[0]["action"] == "deleted"

        check = tmp_path / "check"
        _git(tmp_path, "clone", "-q", str(bare_repo), str(check))
        content = (check / "polara" / "app" / "regra" / "outra.md").read_text(encoding="utf-8")
        assert "relations: []" in content or "relations: []\n" in content.replace("\n\n", "\n")
