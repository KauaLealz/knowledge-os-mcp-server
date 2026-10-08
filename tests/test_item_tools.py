"""Ferramentas de item chamadas como funções Python (sem o protocolo): o que a fila offline e
os scripts usam. Devolvem os dicionários do serviço, sem remodelar."""

import pytest

from knowledge_os.config import NO_CONNECTION_MESSAGE
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.mcp import tools

PROJECT = "github.com/org/app"
RULE = {"type": "rule", "title": "Money em pagamentos", "summary": "Valores em Money",
        "content": "Use Money."}


@pytest.fixture
def linked(conn):
    tools.repo(action="link", repo=PROJECT, workspace="W", project="app")
    return conn


def test_save_get_search_delete(linked):
    (row,) = tools.item_save([{"key": "rule/money", **RULE}], repo=PROJECT)
    assert (row["action"], row["scope"], row["key"]) == ("created", "scoped", "rule/money")
    (got,) = tools.item_get(keys=["rule/money"], repo=PROJECT)
    assert got["id"] == row["id"] and got["where"] == "W/app"
    found = tools.item_search(query="money", repo=PROJECT)
    assert [r["key"] for r in found["results"]] == ["rule/money"]
    assert tools.item_delete(keys=["rule/money"], repo=PROJECT)["status"] == "preview"
    assert tools.item_delete(keys=["rule/money"], repo=PROJECT, confirm=True)["ids"] == [
        row["id"]]
    assert tools.item_get(ids=[row["id"]]) == [{"id": row["id"], "missing": True}]


def test_repo_nao_ligado_e_sem_lugar(linked):
    with pytest.raises(NotFoundError, match=r'repo\(action="link", repo="github.com/o/n"\)'):
        tools.item_save([{"key": "rule/x", **RULE}], repo="github.com/o/n")
    with pytest.raises(ValidationError, match="workspace e project"):
        tools.item_save([{"key": "rule/x", **RULE}])


def test_sem_conexao_da_erro_claro(_isolated_home):
    with pytest.raises(ValidationError) as exc:
        tools.item_save([{"key": "rule/x", **RULE}], repo=PROJECT)
    assert str(exc.value) == NO_CONNECTION_MESSAGE
    assert not (_isolated_home / "connections.json").exists()  # nada é criado
