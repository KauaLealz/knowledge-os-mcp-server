"""Ferramentas MCP ponta a ponta, pelo protocolo (cliente em memória): os 15 tools novos."""

import asyncio
import json
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from src.mcp import admin_tools, agent_tools
from tests.helpers_multidb import catalog  # noqa: F401  (fixture: catálogo isolado)

PROJECT = "github.com/org/app"
RULE = {"type": "rule", "memory_class": "working", "summary": "resumo", "content": "corpo"}


@pytest.fixture
def server(catalog):  # noqa: F811
    m = FastMCP(name="t")
    agent_tools.register(m)
    admin_tools.register(m)
    return m


def call(server: FastMCP, tool: str, /, **args: Any) -> Any:
    async def run() -> Any:
        async with Client(server) as client:
            return await client.call_tool(tool, args)

    result = asyncio.run(run())
    if result.data is not None:
        return result.data
    return json.loads(result.content[0].text)


def fails(server: FastMCP, tool: str, /, **args: Any) -> str:
    with pytest.raises(ToolError) as exc:
        call(server, tool, **args)
    return str(exc.value)


def test_nomes_e_documentacao(server):
    async def names() -> dict[str, str]:
        async with Client(server) as client:
            return {t.name: t.description or "" for t in await client.list_tools()}

    tools = asyncio.run(names())
    assert set(tools) == {
        "context_get", "item_search", "item_get", "item_save", "project_link",
        "structure_list", "structure_delete", "item_delete", "relation_delete", "vocabulary",
        "backup_export", "backup_import", "artifact_attach", "artifact_get",
    }
    for name, doc in tools.items():
        assert "**Use quando:**" in doc and "**Retorna:**" in doc, name


def test_fluxo_do_plumb(server):
    """Ligar projeto → contexto → gravar em lote → buscar → ler → promover → substituir."""
    assert call(server, "context_get", project=PROJECT)["linked"] is False
    call(server, "project_link", project=PROJECT, workspace="Polara", domain="app")

    saved = call(server, "item_save", project=PROJECT, items=[
        {"key": "regra/money", **RULE, "title": "Money em pagamentos",
         "scope_paths": ["src/payments/**"], "source": "PAY-142"},
        {"key": "decisao/pix", "type": "insight", "memory_class": "working",
         "title": "Pix vencido é recusado", "summary": "Recusar, não estornar",
         "content": "Porque o financeiro revisa caso a caso."},
        {"key": "proc/deploy", "type": "procedure", "memory_class": "working",
         "title": "Deploy manual", "summary": "passo a passo antigo", "content": "..."},
    ])
    assert [s["action"] for s in saved] == ["created"] * 3

    ctx = call(server, "context_get", project=PROJECT, paths=["src/payments/Charge.java"])
    md = ctx["markdown"]
    assert "Money em pagamentos" in md and "Pix vencido" in md and "Deploy manual" in md

    found = call(server, "item_search", query="pagamento", project=PROJECT)
    assert found[0]["key"] == "regra/money" and "content" not in found[0]

    (full,) = call(server, "item_get", keys=["regra/money"], project=PROJECT)
    assert full["content"] == "corpo" and full["scope_paths"] == ["src/payments/**"]

    again = call(server, "item_save", project=PROJECT, items=[
        {"id": full["id"], "memory_class": "longterm"},
        {"key": "proc/deploy-ci", "type": "procedure", "memory_class": "working",
         "title": "Deploy no CI", "summary": "pipeline", "content": "...",
         "relations": [{"type": "supersedes", "target": "proc/deploy"}]},
    ])
    assert again[0]["action"] == "updated" and again[1]["relations"] == 1
    (promoted,) = call(server, "item_get", ids=[full["id"]])
    assert promoted["memory_class"] == "longterm"
    titles = [r["title"] for r in call(server, "item_search", query="deploy", project=PROJECT)]
    assert titles == ["Deploy no CI"]  # o substituído saiu da busca
    assert "Deploy manual" in [
        r["title"] for r in call(server, "item_search", query="deploy", project=PROJECT,
                                 include_inactive=True)]


def test_item_save_modos_e_erros(server):
    call(server, "project_link", project=PROJECT, workspace="Polara", domain="app")
    first = call(server, "item_save", project=PROJECT,
                 items=[{**RULE, "title": "Cache com Redis"}])
    assert first[0]["action"] == "created" and "similar" not in first[0]
    second = call(server, "item_save", project=PROJECT,
                  items=[{**RULE, "title": "Redis como cache"}])
    assert second[0]["similar"][0]["title"] == "Cache com Redis"

    unchanged = call(server, "item_save", project=PROJECT,
                     items=[{"key": "k", **RULE, "title": "T"}])
    assert unchanged[0]["action"] == "created"
    assert call(server, "item_save", project=PROJECT,
                items=[{"key": "k", "summary": "resumo"}])[0]["action"] == "unchanged"

    eph = call(server, "item_save", project=PROJECT, items=[
        {"key": "nota", **RULE, "title": "Nota", "memory_class": "ephemeral", "ttl_days": 1}])
    (before,) = call(server, "item_get", ids=[eph[0]["id"]])
    call(server, "item_save", items=[{"id": eph[0]["id"], "ttl_days": 30}])
    (after,) = call(server, "item_get", ids=[eph[0]["id"]])
    assert after["expires_at"] > before["expires_at"]

    msg = fails(server, "item_save", project=PROJECT,
                items=[{"key": "s", **RULE, "title": "x", "content": "password=Segredo123!"}])
    assert "segredo" in msg and "Segredo123" not in msg

    msg = fails(server, "item_save", project=PROJECT, items=[
        {"key": "ok", **RULE, "title": "ok"}, {"key": "ruim", **RULE, "title": "x", "type": "?"}])
    assert "Entrada 1" in msg
    gone = call(server, "item_get", keys=["ok"], project=PROJECT)
    assert gone == [{"key": "ok", "missing": True}]  # o lote foi desfeito

    assert "project" in fails(server, "item_save", items=[{**RULE, "title": "sem lugar"}])
    assert "não ligado" in fails(server, "item_search", query="x", project="github.com/o/n")


def test_administracao(server, tmp_path):
    saved = call(server, "item_save", items=[
        {"workspace": "W", "domain": "D", "key": "a", **RULE, "title": "A", "tags": ["x"]},
        {"workspace": "W", "domain": "D", "key": "b", **RULE, "title": "B",
         "relations": [{"type": "related_to", "target": "a"}]},
    ])
    tree = call(server, "structure_list")
    assert tree == [{"workspace": "W", "description": None, "items": 2,
                     "domains": [{"name": "D", "items": 2}]}]

    assert {"x"} <= {t["name"] for t in call(server, "vocabulary", kind="tags")}
    lab = call(server, "vocabulary", kind="labels", action="create", name="lgpd")
    assert call(server, "vocabulary", kind="labels", action="delete", id=lab["id"])["status"]

    src = tmp_path / "diagrama.txt"
    src.write_text("caixas e setas", encoding="utf-8")
    art = call(server, "artifact_attach", item_id=saved[0]["id"], file_path=str(src))
    (item_a,) = call(server, "item_get", ids=[saved[0]["id"]])
    assert item_a["artifacts"][0]["filename"] == "diagrama.txt"
    assert call(server, "artifact_get", artifact_id=art["id"])["content_base64"]

    (item_b,) = call(server, "item_get", ids=[saved[1]["id"]])
    rel_id = item_b["relations"][0]["id"]
    assert call(server, "relation_delete", relation_id=rel_id)["status"] == "deleted"

    zip_path = call(server, "backup_export", workspace="W")["file_path"]
    preview = call(server, "structure_delete", workspace="W")
    assert preview == {"status": "preview", "would_delete": {"workspace": "W", "domains": 1,
                                                            "items": 2}}
    assert call(server, "structure_list")  # nada apagado sem confirm
    call(server, "structure_delete", workspace="W", confirm=True)
    assert call(server, "structure_list") == []
    restored = call(server, "backup_import", file_path=zip_path)
    assert restored["name"] == "W" and call(server, "structure_list")[0]["items"] == 2

    victim = call(server, "item_search", query="A", workspace="W")[0]["id"]
    assert call(server, "item_delete", item_id=victim)["status"] == "deleted"


def test_busca_sem_projeto_usa_o_da_pasta_e_nao_vaza(server, monkeypatch):
    call(server, "project_link", project=PROJECT, workspace="Polara", domain="app")
    call(server, "item_save", project=PROJECT, items=[
        {"key": "a", **RULE, "title": "Segredo de cobrança do app"}])
    call(server, "project_link", project="github.com/org/outro", workspace="Outra", domain="o")
    call(server, "item_save", project="github.com/org/outro", items=[
        {"key": "b", **RULE, "title": "Segredo de cobrança do outro"}])

    def titles(**kw: Any) -> set[str]:
        return {r["title"] for r in call(server, "item_search", query="cobrança", **kw)}

    assert len(titles()) == 2  # pasta não ligada: busca em todos (comportamento anterior)
    from src.services.project_service import ProjectService
    real = ProjectService.resolve
    monkeypatch.setattr(ProjectService, "resolve", lambda self, p: real(
        self, PROJECT if p == "." else p))
    assert titles() == {"Segredo de cobrança do app"}  # pasta ligada: só o projeto
    assert len(titles(everywhere=True)) == 2
