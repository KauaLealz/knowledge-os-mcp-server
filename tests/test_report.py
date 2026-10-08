"""`knowledge-mcp report` (V2_MVP.md §10): o relatório para o plumb-dream — nunca abertos há
60 dias, em review há mais de 7, alta taxa de irrelevante, buscas vazias e tags sem uso."""

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
    novo = _save("rule/novo")
    revisao = _save("rule/revisao", status="review")
    _age(revisao, 8, field="updated_at")
    revisao_nova = _save("rule/revisao-nova", status="review")
    ruim = _save("rule/ruim")
    bom = _save("rule/bom")
    cid = Brain().cid
    local_state.count(cid, [aberto], "opened")
    for _ in range(3):
        local_state.count(cid, [ruim, bom], "irrelevant")
    for _ in range(3):
        local_state.count(cid, [bom], "helped")
    ItemService().search("consulta que nao acha nada", viewpoint=None)
    ItemService().search("Consulta que  nao acha nada", viewpoint=None)
    TagService().create(["sem-uso"])
    _save("rule/com-tag", tags=["usada"])
    return {"novo": novo, "revisao_nova": revisao_nova}


def test_report_json(cenario, capsys):
    data = json.loads(_report(capsys, "--json"))
    assert set(data) == {"never_opened_60d", "review_over_7d", "high_irrelevant",
                         "empty_searches", "tags_unused"}
    assert [r["key"] for r in data["never_opened_60d"]] == ["rule/velho"]
    assert [r["key"] for r in data["review_over_7d"]] == ["rule/revisao"]
    assert [r["key"] for r in data["high_irrelevant"]] == ["rule/ruim"]
    for name in ("never_opened_60d", "review_over_7d", "high_irrelevant"):
        row = data[name][0]
        assert row["where"] == "W/P" and row["reason"]
    assert data["empty_searches"] == [{"query": "consulta que nao acha nada", "count": 2}]
    assert [t["name"] for t in data["tags_unused"]] == ["sem-uso"]


def test_report_legivel(cenario, capsys):
    out = _report(capsys)
    assert "rule/velho" in out and "rule/revisao" in out and "rule/ruim" in out
    assert "consulta que nao acha nada" in out and "sem-uso" in out


def test_report_vazio(conn, capsys):
    data = json.loads(_report(capsys, "--json"))
    assert data == {"never_opened_60d": [], "review_over_7d": [], "high_irrelevant": [],
                    "empty_searches": [], "tags_unused": []}
    assert "nada a revisar" in _report(capsys).lower()
