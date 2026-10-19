"""Item que mora no nível do workspace (sem project): vale no workspace inteiro e abaixo."""

from knowledge_os.services.brain import Brain
from knowledge_os.services.item_service import ItemService


def test_item_no_nivel_do_workspace_grava_na_pasta_reservada(conn):
    isv = ItemService()
    row = isv.save([{"workspace": "Banco", "key": "rule/global", "type": "rule",
                     "title": "G", "summary": "s", "content": "c"}])[0]
    assert row["action"] == "created"
    rec = Brain().snapshot.get(row["id"])
    assert rec.workspace == "Banco" and rec.project is None
    assert rec.path == "banco/_/rule/global.md"  # pasta reservada "_", não colide com project


def test_item_do_workspace_alcanca_os_projects(conn):
    isv = ItemService()
    isv.save([{"workspace": "Banco", "key": "rule/global", "type": "rule",
               "title": "Regra do banco", "summary": "vale em tudo", "content": "c"}])
    isv.save([{"workspace": "Banco", "project": "app", "key": "rule/x", "type": "rule",
               "title": "X", "summary": "s", "content": "c"}])
    # Um project do mesmo workspace enxerga a regra que mora no workspace.
    hits = isv.search("banco", viewpoint=("banco", "app"))
    assert "rule/global" in [h["key"] for h in hits["results"]]


def test_project_nao_cria_pasta_para_item_do_workspace(conn):
    isv = ItemService()
    isv.save([{"workspace": "Banco", "key": "rule/global", "type": "rule",
               "title": "G", "summary": "s", "content": "c"}])
    # A pasta reservada "_" não vira um project na árvore.
    assert Brain().snapshot.projects("banco") == []
