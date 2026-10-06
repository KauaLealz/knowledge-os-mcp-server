"""Ferramentas MCP ponta a ponta, pelo protocolo (cliente em memória): os 13 tools de tools.py
(mais health_check, registrado à parte em main.py — não entra no fixture `server`)."""

import asyncio
import json
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from knowledge_os.mcp import tools
from tests.helpers_multidb import catalog  # noqa: F401  (fixture: catálogo isolado)

PROJECT = "github.com/org/app"
RULE = {"type": "rule", "memory_class": "working", "summary": "resumo", "content": "corpo"}


@pytest.fixture
def server(catalog):  # noqa: F811
    m = FastMCP(name="t")
    tools.register(m)
    return m


def call(server: FastMCP, tool: str, /, **args: Any) -> Any:
    async def run() -> Any:
        async with Client(server) as client:
            return await client.call_tool(tool, args)

    result = asyncio.run(run())
    if result.data is not None:
        return result.data
    if not result.content:
        return []  # ferramentas com retorno `Any` não estruturam uma lista vazia
    return json.loads(result.content[0].text)


def fails(server: FastMCP, tool: str, /, **args: Any) -> str:
    with pytest.raises(ToolError) as exc:
        call(server, tool, **args)
    return str(exc.value)


def test_nomes_e_documentacao(server):
    async def names() -> dict[str, str]:
        async with Client(server) as client:
            return {t.name: t.description or "" for t in await client.list_tools()}

    tools_ = asyncio.run(names())
    assert set(tools_) == {
        "workspace", "project", "subject", "repo",
        "context_get", "item_search", "item_get", "item_save",
        "item_delete", "relation_delete", "vocabulary",
        "artifact", "backup",
    }
    for name, doc in tools_.items():
        assert "**Use quando:**" in doc and "**Retorna:**" in doc, name


def test_fluxo_do_plumb(server):
    """Ligar projeto → contexto → gravar em lote → buscar → ler → promover → substituir."""
    assert call(server, "context_get", repo=PROJECT)["linked"] is False
    call(server, "repo", action="link", repo=PROJECT, workspace="Polara", project="app")

    saved = call(server, "item_save", repo=PROJECT, items=[
        {"key": "regra/money", **RULE, "title": "Money em pagamentos",
         "scope_paths": ["src/payments/**"], "source": "PAY-142"},
        {"key": "decisao/pix", "type": "insight", "memory_class": "working",
         "title": "Pix vencido é recusado", "summary": "Recusar, não estornar",
         "content": "Porque o financeiro revisa caso a caso."},
        {"key": "proc/deploy", "type": "procedure", "memory_class": "working",
         "title": "Deploy manual", "summary": "passo a passo antigo", "content": "..."},
    ])
    assert [s["action"] for s in saved] == ["created"] * 3

    ctx = call(server, "context_get", repo=PROJECT, paths=["src/payments/Charge.java"])
    md = ctx["markdown"]
    assert "Money em pagamentos" in md and "Pix vencido" in md and "Deploy manual" in md

    found = call(server, "item_search", query="pagamento", repo=PROJECT)
    assert found[0]["key"] == "regra/money" and "content" not in found[0]

    (full,) = call(server, "item_get", keys=["regra/money"], repo=PROJECT)
    assert full["content"] == "corpo" and full["scope_paths"] == ["src/payments/**"]

    again = call(server, "item_save", repo=PROJECT, items=[
        {"id": full["id"], "memory_class": "longterm"},
        {"key": "proc/deploy-ci", "type": "procedure", "memory_class": "working",
         "title": "Deploy no CI", "summary": "pipeline", "content": "...",
         "relations": [{"type": "supersedes", "target": "proc/deploy"}]},
    ])
    assert again[0]["action"] == "updated" and again[1]["relations"] == 1
    (promoted,) = call(server, "item_get", ids=[full["id"]])
    assert promoted["memory_class"] == "longterm"
    titles = [r["title"] for r in call(server, "item_search", query="deploy", repo=PROJECT)]
    assert titles == ["Deploy no CI"]  # o substituído saiu da busca
    assert "Deploy manual" in [
        r["title"] for r in call(server, "item_search", query="deploy", repo=PROJECT,
                                 include_inactive=True)]


def test_item_save_modos_e_erros(server):
    call(server, "repo", action="link", repo=PROJECT, workspace="Polara", project="app")
    first = call(server, "item_save", repo=PROJECT,
                 items=[{**RULE, "title": "Cache com Redis"}])
    assert first[0]["action"] == "created" and "similar" not in first[0]
    second = call(server, "item_save", repo=PROJECT,
                  items=[{**RULE, "title": "Redis como cache"}])
    assert second[0]["similar"][0]["title"] == "Cache com Redis"

    unchanged = call(server, "item_save", repo=PROJECT,
                     items=[{"key": "k", **RULE, "title": "T"}])
    assert unchanged[0]["action"] == "created"
    assert call(server, "item_save", repo=PROJECT,
                items=[{"key": "k", "summary": "resumo"}])[0]["action"] == "unchanged"

    eph = call(server, "item_save", repo=PROJECT, items=[
        {"key": "nota", **RULE, "title": "Nota", "memory_class": "ephemeral", "ttl_days": 1}])
    (before,) = call(server, "item_get", ids=[eph[0]["id"]])
    call(server, "item_save", items=[{"id": eph[0]["id"], "ttl_days": 30}])
    (after,) = call(server, "item_get", ids=[eph[0]["id"]])
    assert after["expires_at"] > before["expires_at"]

    msg = fails(server, "item_save", repo=PROJECT,
                items=[{"key": "s", **RULE, "title": "x", "content": "password=Segredo123!"}])
    assert "segredo" in msg and "Segredo123" not in msg

    msg = fails(server, "item_save", repo=PROJECT, items=[
        {"key": "ok", **RULE, "title": "ok"}, {"key": "ruim", **RULE, "title": "x", "type": "?"}])
    assert "Entrada 1" in msg
    gone = call(server, "item_get", keys=["ok"], repo=PROJECT)
    assert gone == [{"key": "ok", "missing": True}]  # o lote foi desfeito

    assert "repo" in fails(server, "item_save", items=[{**RULE, "title": "sem lugar"}])
    assert "não ligado" in fails(server, "item_search", query="x", repo="github.com/o/n")


def test_administracao(server, tmp_path):
    saved = call(server, "item_save", items=[
        {"workspace": "W", "project": "D", "key": "a", **RULE, "title": "A", "tags": ["x"]},
        {"workspace": "W", "project": "D", "key": "b", **RULE, "title": "B",
         "relations": [{"type": "related_to", "target": "a"}]},
    ])
    tree = call(server, "workspace", action="list")
    assert tree == [{"name": "W", "description": None, "items": 2, "projects": 1}]
    assert call(server, "project", action="list", workspace="W") == [{"name": "D", "items": 2}]

    assert {"x"} <= {t["name"] for t in call(server, "vocabulary", kind="tags")}
    lab = call(server, "vocabulary", kind="labels", action="create", name="lgpd")
    assert call(server, "vocabulary", kind="labels", action="delete", id=lab["id"])["status"]

    src = tmp_path / "diagrama.txt"
    src.write_text("caixas e setas", encoding="utf-8")
    art = call(server, "artifact", action="attach", item_id=saved[0]["id"], file_path=str(src))
    (item_a,) = call(server, "item_get", ids=[saved[0]["id"]])
    assert item_a["artifacts"][0]["filename"] == "diagrama.txt"
    assert call(server, "artifact", action="get", artifact_id=art["id"])["content_base64"]

    (item_b,) = call(server, "item_get", ids=[saved[1]["id"]])
    rel_id = item_b["relations"][0]["id"]
    assert call(server, "relation_delete", relation_id=rel_id)["status"] == "deleted"

    zip_path = call(server, "backup", action="export", workspace="W")["file_path"]
    preview = call(server, "workspace", action="delete", name="W")
    assert preview == {"status": "preview", "would_delete": {"workspace": "W", "projects": 1,
                                                            "items": 2}}
    assert call(server, "workspace", action="list")  # nada apagado sem confirm
    call(server, "workspace", action="delete", name="W", confirm=True)
    assert call(server, "workspace", action="list") == []
    restored = call(server, "backup", action="import", file_path=zip_path)
    assert restored["name"] == "W" and call(server, "workspace", action="list")[0]["items"] == 2

    victim = call(server, "item_search", query="A", workspace="W")[0]["id"]
    assert call(server, "item_delete", item_id=victim)["status"] == "deleted"


def test_workspace_project_subject_rename_e_merge(server):
    call(server, "item_save", items=[
        {"workspace": "src-ws", "project": "src-pj", "key": "a", **RULE, "title": "A"},
    ])
    call(server, "workspace", action="create", name="tgt-ws")

    renamed_pj = call(server, "project", action="rename", workspace="src-ws",
                      name="src-pj", new_name="pj2")
    assert renamed_pj["name"] == "pj2"

    renamed_sj = call(server, "subject", action="create", workspace="src-ws", project="pj2",
                      name="s1")
    assert renamed_sj["name"] == "s1"
    renamed_sj2 = call(server, "subject", action="rename", workspace="src-ws", project="pj2",
                       name="s1", new_name="s2")
    assert renamed_sj2["name"] == "s2"

    result = call(server, "workspace", action="merge", source="src-ws", target="tgt-ws")
    assert result == {"merged_projects": 1, "renamed_collisions": 0}
    assert [p["name"] for p in call(server, "project", action="list", workspace="tgt-ws")] == \
        ["pj2"]
    assert fails(server, "workspace", action="rename", name="nao-existe", new_name="x")


def test_subject_delete_preview_nao_apaga_item(server):
    call(server, "item_save", items=[
        {"workspace": "W", "project": "D", "key": "a", **RULE, "title": "A",
         "subject": "assunto-x"},
    ])
    preview = call(server, "subject", action="delete", workspace="W", project="D",
                   name="assunto-x")
    assert preview == {"status": "preview", "would_delete": {"subject": "assunto-x",
                                                              "items_sem_assunto": 1}}
    deleted = call(server, "subject", action="delete", workspace="W", project="D",
                   name="assunto-x", confirm=True)
    assert deleted["status"] == "deleted"
    (item,) = call(server, "item_get", keys=["a"], workspace="W", project="D")
    assert item["id"]  # item continua existindo


def test_repo_list_unlink_e_candidate_match(server):
    call(server, "workspace", action="create", name="AI8")
    out = call(server, "repo", action="link", repo="path:/tmp/ai8-repo-x", workspace="ai8",
               project="algo")
    assert out == {"status": "candidate",
                   "candidate_match": {"field": "workspace", "input": "ai8", "candidate": "AI8"}}

    confirmed = call(server, "repo", action="link", repo="path:/tmp/ai8-repo-x",
                     workspace="ai8", project="algo", confirm_new=True)
    assert confirmed["workspace"] == "ai8"

    links = call(server, "repo", action="list", workspace="ai8")
    assert links == [{"repo_key": "path:/tmp/ai8-repo-x", "workspace": "ai8", "project": "algo"}]

    assert call(server, "repo", action="unlink",
                repo="path:/tmp/ai8-repo-x")["status"] == "deleted"
    assert call(server, "repo", action="list", workspace="ai8") == []
    assert "não ligado" in fails(server, "repo", action="unlink", repo="path:/tmp/ai8-repo-x")


def test_busca_sem_projeto_usa_o_da_pasta_e_nao_vaza(server, monkeypatch):
    call(server, "repo", action="link", repo=PROJECT, workspace="Polara", project="app")
    call(server, "item_save", repo=PROJECT, items=[
        {"key": "a", **RULE, "title": "Segredo de cobrança do app"}])
    call(server, "repo", action="link", repo="github.com/org/outro", workspace="Outra",
         project="o")
    call(server, "item_save", repo="github.com/org/outro", items=[
        {"key": "b", **RULE, "title": "Segredo de cobrança do outro"}])

    def titles(**kw: Any) -> set[str]:
        return {r["title"] for r in call(server, "item_search", query="cobrança", **kw)}

    assert len(titles()) == 2  # pasta não ligada: busca em todos (comportamento anterior)
    from knowledge_os.services.repo_service import RepoService
    real = RepoService.resolve
    monkeypatch.setattr(RepoService, "resolve", lambda self, p: real(
        self, PROJECT if p == "." else p))
    assert titles() == {"Segredo de cobrança do app"}  # pasta ligada: só o projeto
    assert len(titles(everywhere=True)) == 2


def test_item_get_conta_uso(server):
    call(server, "repo", action="link", repo=PROJECT, workspace="W", project="app")
    call(server, "item_save", repo=PROJECT, items=[{"key": "r", "title": "R", **RULE}])
    assert call(server, "item_get", keys=["r"], repo=PROJECT)[0]["access_count"] == 0
    assert call(server, "item_get", keys=["r"], repo=PROJECT)[0]["access_count"] == 1


def test_item_search_filtra_por_subject(server):
    call(server, "repo", action="link", repo=PROJECT, workspace="Polara", project="app")
    call(server, "item_save", repo=PROJECT, items=[
        {"key": "a", **RULE, "title": "Item do assunto X", "subject": "assunto-x"},
        {"key": "b", **RULE, "title": "Item do assunto Y", "subject": "assunto-y"},
        {"key": "c", **RULE, "title": "Item sem assunto"},
    ])
    titles = {r["title"] for r in call(server, "item_search", query="Item", repo=PROJECT,
                                        project="app", subject="assunto-x")}
    assert titles == {"Item do assunto X"}
    assert "subject" in fails(server, "item_search", query="Item", subject="assunto-x")


def test_item_save_move_por_id_preserva_id_created_at_e_access_count(server):
    call(server, "repo", action="link", repo=PROJECT, workspace="Polara", project="app")
    saved = call(server, "item_save", repo=PROJECT,
                 items=[{"key": "a", **RULE, "title": "Vai mudar de lugar"}])
    item_id = saved[0]["id"]
    # item_get conta uso: a leitura "antes" já bumpa o access_count em 1.
    (before,) = call(server, "item_get", ids=[item_id])

    moved = call(server, "item_save", items=[
        {"id": item_id, "workspace": "OutroWorkspace", "project": "outro-project"}])
    assert moved[0]["action"] == "updated"

    (after,) = call(server, "item_get", ids=[item_id])
    assert after["id"] == before["id"]
    assert after["created_at"] == before["created_at"]
    # Só o item_get seguinte bumpou de novo: o move em si não mexeu no access_count.
    assert after["access_count"] == before["access_count"] + 1
    assert after["workspace_id"] != before["workspace_id"]
    assert after["project_id"] != before["project_id"]
    assert after["subject_id"] is None  # mudou de project sem informar subject: zera

    found = call(server, "item_search", query="mudar", workspace="OutroWorkspace")
    assert found and found[0]["id"] == item_id


def test_item_save_move_so_o_subject(server):
    call(server, "repo", action="link", repo=PROJECT, workspace="Polara", project="app")
    saved = call(server, "item_save", repo=PROJECT,
                 items=[{"key": "a", **RULE, "title": "Vai ganhar assunto"}])
    item_id = saved[0]["id"]
    (before,) = call(server, "item_get", ids=[item_id])

    moved = call(server, "item_save", items=[{"id": item_id, "subject": "novo-assunto"}])
    assert moved[0]["action"] == "updated"

    (after,) = call(server, "item_get", ids=[item_id])
    assert after["id"] == before["id"]
    assert after["created_at"] == before["created_at"]
    assert after["workspace_id"] == before["workspace_id"]
    assert after["project_id"] == before["project_id"]
    assert after["subject_id"] is not None

    found = call(server, "item_search", query="assunto", repo=PROJECT, project="app",
                 subject="novo-assunto")
    assert found and found[0]["id"] == item_id
