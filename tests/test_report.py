"""`knowledge-mcp report` (v6): o relatório para o plumb-reflect — nunca abertos há 60 dias,
arquivados (candidatos a remover), buscas vazias e tags sem uso."""

import dataclasses
import json
from datetime import timedelta

import pytest

from knowledge_os import cli
from knowledge_os.services.brain import Brain, utcnow
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.tag_service import TagService
from knowledge_os.storage import local_state


def _save(key, **extra):
    entry = {"workspace": "W", "project": "P", "key": key, "type": "rule", "title": key,
             "summary": "s", "content": "c", **extra}
    return ItemService().save([entry])[0]["id"]


def _age(item_id, days, field="created_at"):
    brain = Brain()
    with brain.editing() as d:
        record = d.require(item_id)
        when = utcnow() - timedelta(days=days)
        changes = {field: when}
        if field == "created_at":
            changes["updated_at"] = when
        d.put(dataclasses.replace(record, **changes))
        brain.commit(d, "envelhece")


def _report(capsys, *args):
    assert cli.main(["report", *args]) == 0
    return capsys.readouterr().out


@pytest.fixture
def cenario(conn):
    velho = _save("rule/velho")
    _age(velho, 61)
    aberto = _save("rule/velho-aberto")
    _age(aberto, 61)
    _save("rule/novo")
    _save("rule/arquivado", tags=["archived"])
    cid = Brain().cid
    local_state.count(cid, [aberto], "opened")
    ItemService().search("consulta que nao acha nada", viewpoint=None)
    ItemService().search("Consulta que  nao acha nada", viewpoint=None)
    TagService().create(["sem-uso"])
    _save("rule/com-tag", tags=["usada"])
    return {}


def test_report_json(cenario, capsys):
    data = json.loads(_report(capsys, "--json"))
    assert set(data) == {"never_opened_60d", "archived", "empty_searches", "tags_unused"}
    assert [r["key"] for r in data["never_opened_60d"]] == ["rule/velho"]
    assert [r["key"] for r in data["archived"]] == ["rule/arquivado"]
    for name in ("never_opened_60d", "archived"):
        row = data[name][0]
        assert row["where"] == "W/P" and row["reason"]
    assert data["empty_searches"] == [{"query": "consulta que nao acha nada", "count": 2}]
    assert [t["name"] for t in data["tags_unused"]] == ["sem-uso"]


def test_report_legivel(cenario, capsys):
    out = _report(capsys)
    assert "rule/velho" in out and "rule/arquivado" in out
    assert "consulta que nao acha nada" in out and "sem-uso" in out


def test_report_vazio(conn, capsys):
    data = json.loads(_report(capsys, "--json"))
    assert data == {"never_opened_60d": [], "archived": [], "empty_searches": [],
                    "tags_unused": []}
    assert "nada a revisar" in _report(capsys).lower()
