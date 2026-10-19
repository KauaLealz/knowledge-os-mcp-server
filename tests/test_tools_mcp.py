"""Ferramentas MCP v6 ponta a ponta, pelo protocolo (cliente em memória): as 31 de `tools.py`
(sem `item_feedback`), cada uma orquestrando o serviço dela. Alcance por hierarquia (o item
vale onde mora na árvore workspace → project → subject e abaixo); não há scope/subtype/status."""

import asyncio
import json
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from knowledge_os.mcp import tools

PROJECT = "github.com/org/app"
OTHER = "github.com/org/outro"
RULE = {"type": "rule", "summary": "resumo", "content": "corpo"}


@pytest.fixture
def server(conn):
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
        return []
    return json.loads(result.content[0].text)


def fails(server: FastMCP, tool: str, /, **args: Any) -> str:
    with pytest.raises(ToolError) as exc:
        call(server, tool, **args)
    return str(exc.value)


def link(server: FastMCP, repo: str, workspace: str, project: str) -> None:
    call(server, "repo", action="link", repo=repo, workspace=workspace, project=project)


@pytest.fixture
def chain(server):
    """W/app (o repositório) e W/outro; uma regra em cada project. O alcance é por hierarquia:
    de W/app só se enxerga app (e seus subjects), não o project outro."""
    link(server, PROJECT, "W", "app")
    link(server, OTHER, "W", "outro")
    call(server, "item_save", repo=PROJECT, items=[
        {"key": "rule/money", **RULE, "title": "Money em pagamentos",
         "links": [{"path": "src/payments/**"}], "content": "Use Money, nunca double."},
        {"key": "rule/dois", **RULE, "title": "Segunda regra de pagamentos"}])
    call(server, "item_save", repo=OTHER, items=[
        {"key": "rule/so-outro", **RULE, "title": "Regra só de outro pagamentos"}])
    return server


# ---- item_save / item_get / item_search ---------------------------------------------------


def test_item_get_resolve_keys_pela_cadeia(chain):
    got = call(chain, "item_get", keys=["rule/money", "rule/so-outro"], repo=PROJECT)
    assert got[0].get("where") == "W/app"
    assert got[0]["content"] == "Use Money, nunca double."
    # rule/so-outro mora em W/outro, fora do alcance de W/app: não resolve pela key daqui.
    assert got[1] == {"key": "rule/so-outro", "missing": True}
    assert call(chain, "item_get", keys=["rule/so-outro"], workspace="W", project="outro")[0][
        "title"]
    assert call(chain, "item_get", ids=[got[0]["id"]])[0]["key"] == "rule/money"


def test_item_save_upsert_por_key_e_lote_de_21(chain):
    (before,) = call(chain, "item_get", keys=["rule/money"], repo=PROJECT)
    (row,) = call(chain, "item_save", repo=PROJECT,
                  items=[{"key": "rule/money", "summary": "Valores sempre em Money"}])
    assert row["action"] == "updated" and row["id"] == before["id"] and row["warnings"] == []
    assert call(chain, "item_save", repo=PROJECT, items=[
        {"key": "rule/money", "summary": "Valores sempre em Money"}])[0]["action"] == "unchanged"
    many = [{"key": f"rule/r{i}", **RULE, "title": f"R{i}"} for i in range(21)]
    assert "no máximo 20" in fails(chain, "item_save", repo=PROJECT, items=many)
    assert "no máximo 20" in fails(chain, "item_get", keys=[f"rule/r{i}" for i in range(21)],
                                   repo=PROJECT)


def test_item_save_tag_nova_avisa(server):
    link(server, PROJECT, "W", "app")
    (row,) = call(server, "item_save", repo=PROJECT, items=[
        {"key": "rule/pix", "type": "rule", "title": "Pix vencido",
         "summary": "Recusar", "content": "Recusar.", "tags": ["pix-novo"]}])
    assert "pix-novo" in " ".join(row["warnings"])


def test_item_search_cadeia_de_alcance(chain):
    found = call(chain, "item_search", query="pagamentos", repo=PROJECT)
    by_key = {r["key"]: r for r in found["results"]}
    # De W/app só se enxerga app; não o project outro.
    assert set(by_key) == {"rule/money", "rule/dois"}
    assert by_key["rule/money"]["where"] == "W/app" and "content" not in by_key["rule/money"]
    whole = call(chain, "item_search", query="pagamentos", workspace="W")
    assert {r["key"] for r in whole["results"]} == {"rule/money", "rule/dois", "rule/so-outro"}
    everything = call(chain, "item_search", query="pagamentos", everywhere=True)
    assert "rule/so-outro" in {r["key"] for r in everything["results"]}


def test_item_search_queries_em_lote_e_paths(chain):
    out = call(chain, "item_search", queries=["money", "segunda"], repo=PROJECT)
    assert [g["query"] for g in out["groups"]] == ["money", "segunda"]
    assert "no máximo 5" in fails(chain, "item_search", queries=list("abcdef"), repo=PROJECT)
    (hit, *_) = call(chain, "item_search", query="money", repo=PROJECT,
                     paths=["src/payments/Charge.java"])["results"]
    assert hit["key"] == "rule/money" and "path" in hit["matched_in"]
    assert hit["excerpt"].startswith("Use Money")


def test_item_search_sem_consulta_traz_o_essencial(chain):
    out = call(chain, "item_search", repo=PROJECT)
    assert "rule/money" in {r["key"] for g in out["groups"] for r in g["results"]}


def test_item_search_pasta_nao_ligada_so_globais_com_sugestao(chain):
    out = call(chain, "item_search", query="pagamentos")
    assert 'repo(action="link"' in out["suggestion"]


# ---- item_delete --------------------------------------------------------------------------


def test_item_delete_candidatos_previa_e_confirm(chain):
    call(chain, "item_save", repo=PROJECT, items=[
        {"key": "rule/velha", **RULE, "title": "Velha", "tags": ["archived"]},
        {"key": "rule/aponta", **RULE, "title": "Aponta",
         "links": [{"item": "rule/velha", "rel": "relates_to"}]}])
    assert "candidates" in call(chain, "item_delete", repo=PROJECT)
    preview = call(chain, "item_delete", repo=PROJECT, keys=["rule/velha"])
    assert preview["status"] == "preview"
    assert call(chain, "item_get", keys=["rule/velha"], repo=PROJECT)[0]["title"] == "Velha"
    gone = call(chain, "item_delete", repo=PROJECT, keys=["rule/velha"], confirm=True)
    assert gone["status"] == "deleted" and len(gone["ids"]) == 1
    assert call(chain, "item_get", keys=["rule/velha"], repo=PROJECT)[0]["missing"] is True


# ---- relações (links item→item) e grafo --------------------------------------------------


def test_relation_create_delete_e_item_graph(chain):
    rel = {"source": "rule/money", "type": "depends_on", "target": "rule/dois"}
    assert call(chain, "relation_create", repo=PROJECT, items=[rel])[0]["action"] == "created"
    assert call(chain, "relation_create", repo=PROJECT, items=[rel])[0]["action"] == "unchanged"
    graph = call(chain, "item_graph", keys=["rule/money"], repo=PROJECT)
    assert {n["key"]: n["hop"] for n in graph["nodes"]} == {"rule/money": 0, "rule/dois": 1}
    assert graph["edges"] == [{"from": "rule/money", "type": "depends_on", "to": "rule/dois"}]
    only_in = call(chain, "item_graph", keys=["rule/money"], repo=PROJECT, direction="in")
    assert [n["key"] for n in only_in["nodes"]] == ["rule/money"]
    assert call(chain, "relation_delete", repo=PROJECT, items=[rel])[0]["action"] == "deleted"
    assert call(chain, "item_graph", keys=["rule/money"], repo=PROJECT)["edges"] == []
    msg = fails(chain, "relation_create", repo=PROJECT, items=[{**rel, "type": "usa"}])
    assert "depends_on" in msg and "relates_to" in msg
    assert "no máximo 5" in fails(chain, "item_graph", keys=list("abcdef"), repo=PROJECT)


# ---- tags ---------------------------------------------------------------------------------


def test_tags_gerenciadas(server):
    link(server, PROJECT, "W", "app")
    assert call(server, "tag_create", names=["lgpd", "pix"]) == {"created": ["lgpd", "pix"],
                                                                 "existing": []}
    call(server, "item_save", repo=PROJECT, items=[
        {"key": "rule/a", **RULE, "title": "A", "tags": ["pix"]}])
    assert call(server, "tag_list") == [{"name": "lgpd", "count": 0}, {"name": "pix", "count": 1}]
    assert call(server, "tag_update", name="pix", new_name="pagamento-pix") == {
        "renamed": 1, "merged": False}
    assert call(server, "item_get", keys=["rule/a"], repo=PROJECT)[0]["tags"] == ["pagamento-pix"]
    preview = call(server, "tag_delete", names=["pagamento-pix"])
    assert preview == {"status": "preview", "tags": [{"name": "pagamento-pix", "items": 1}]}
    assert call(server, "tag_delete", names=["pagamento-pix"], confirm=True)["status"] == "deleted"
    assert call(server, "tag_list") == [{"name": "lgpd", "count": 0}]
    assert "lgpd" in fails(server, "tag_delete", names=["nao-existe"])


# ---- organização --------------------------------------------------------------------------


def test_workspace_crud_e_previa(server):
    ws = call(server, "workspace_create", name="Polara", description="cliente")
    assert (ws["name"], ws["description"]) == ("Polara", "cliente")
    call(server, "workspace_create", name="Velho")
    assert [r["name"] for r in call(server, "workspace_list")] == ["Polara", "Velho"]
    up = call(server, "workspace_update", name="Velho", new_name="Antigo")
    assert up["name"] == "Antigo"
    call(server, "item_save", items=[
        {"workspace": "Antigo", "project": "p", "key": "rule/a", **RULE, "title": "A"}])
    preview = call(server, "workspace_delete", name="Antigo")
    assert preview == {"status": "preview",
                       "would_delete": {"workspace": "Antigo", "projects": 1, "items": 1}}
    assert len(call(server, "workspace_list")) == 2
    assert call(server, "workspace_merge", source="Antigo", target="Polara") == {
        "merged_projects": 1, "renamed_collisions": 0}
    done = call(server, "workspace_delete", name="Polara", confirm=True)
    assert done["status"] == "deleted" and done["items"] == 1
    assert call(server, "workspace_list") == []


def test_project_e_subject_crud(server):
    call(server, "workspace_create", name="W")
    pj = call(server, "project_create", workspace="W", name="app")
    assert pj["name"] == "app"
    call(server, "project_create", workspace="W", name="app-old")
    up = call(server, "project_update", workspace="W", name="app-old", description="legado")
    assert up["description"] == "legado"
    call(server, "subject_create", workspace="W", project="app", name="pagamentos")
    call(server, "subject_create", workspace="W", project="app", name="pagto")
    assert call(server, "subject_update", workspace="W", project="app", name="pagto",
                new_name="cobranca")["name"] == "cobranca"
    call(server, "item_save", items=[{"workspace": "W", "project": "app", "subject": "cobranca",
                                      "key": "rule/a", **RULE, "title": "A"}])
    subjects = call(server, "subject_list", workspace="W", project="app")
    assert [(s["name"], s["items"]) for s in subjects] == [("cobranca", 1), ("pagamentos", 0)]
    assert call(server, "subject_merge", workspace="W", project="app", source="cobranca",
                target="pagamentos") == {"merged_items": 1}
    call(server, "subject_delete", workspace="W", project="app", name="pagamentos", confirm=True)
    (item,) = call(server, "item_get", keys=["rule/a"], workspace="W", project="app")
    assert item["subject"] is None
    assert call(server, "project_merge", workspace="W", source="app-old", target="app")
    call(server, "project_delete", workspace="W", name="app", confirm=True)
    assert call(server, "project_list", workspace="W") == []


# ---- repo / connection --------------------------------------------------------------------


def test_repo_link_list_unlink_candidate_e_sync(server):
    call(server, "workspace_create", name="AI8")
    out = call(server, "repo", action="link", repo="path:/tmp/ai8-repo-x", workspace="ai8",
               project="algo")
    assert out == {"status": "candidate",
                   "candidate_match": {"field": "workspace", "input": "ai8", "candidate": "AI8"}}
    confirmed = call(server, "repo", action="link", repo="path:/tmp/ai8-repo-x",
                     workspace="ai8", project="algo", confirm_new=True)
    assert confirmed["workspace"] == "AI8"
    assert call(server, "repo", action="list", workspace="ai8") == [
        {"repo_key": "path:/tmp/ai8-repo-x", "workspace": "AI8", "project": "algo"}]
    assert call(server, "repo", action="unlink",
                repo="path:/tmp/ai8-repo-x")["status"] == "deleted"
    assert call(server, "repo", action="sync") == {"synced": False}


def test_connection_create_list_delete(_isolated_home, tmp_path):
    m = FastMCP(name="t")
    tools.register(m)
    created = call(m, "connection_create", name="Pessoal", path=str(tmp_path / "pasta"))
    assert created["name"] == "Pessoal" and created["is_default"] is True
    assert [c["name"] for c in call(m, "connection_list")] == ["Pessoal"]
    assert call(m, "connection_delete", id=created["id"]) == {"status": "deleted",
                                                             "id": created["id"]}
    assert call(m, "connection_list") == []
    assert (tmp_path / "pasta").is_dir()


# ---- health_check -------------------------------------------------------------------------


def test_health_check_com_md_quebrado(server, data_dir):
    call(server, "item_save", items=[
        {"workspace": "W", "project": "p", "key": "rule/a", **RULE, "title": "A"}])
    (data_dir / "w" / "p" / "quebrado.md").write_text("---\nid: [sem fim\n---\n", encoding="utf-8")
    report = call(server, "health_check")
    assert set(report) >= {"status", "version", "connections", "gh_authenticated"}
    (conn,) = report["connections"]
    assert conn["name"] == "Teste" and conn["ok"] is True
    assert [e["path"] for e in conn["parse_errors"]] == ["w/p/quebrado.md"]


# ---- erros que dizem como corrigir --------------------------------------------------------


def test_repo_nao_ligado_diz_a_chamada_que_resolve(server):
    hint = 'repo(action="link", repo="github.com/o/n")'
    entry = {"key": "rule/x", **RULE, "title": "X"}
    assert hint in fails(server, "item_save", repo="github.com/o/n", items=[entry])
    rel = {"source": "rule/x", "type": "relates_to", "target": "rule/y"}
    assert hint in fails(server, "relation_create", repo="github.com/o/n", items=[rel])
    assert "repo" in fails(server, "item_save", items=[entry])


def test_tipo_invalido_lista_os_validos(server):
    link(server, PROJECT, "W", "app")
    msg = fails(server, "item_save", repo=PROJECT, items=[
        {"key": "rule/ok", **RULE, "title": "ok"},
        {"key": "rule/x", **RULE, "title": "x", "type": "insight"}])
    assert "Entrada 1" in msg and "rule, howto, context, work, secret" in msg
    assert call(server, "item_get", keys=["rule/ok"], repo=PROJECT) == [
        {"key": "rule/ok", "missing": True}]  # o lote foi desfeito
    assert "desconhecido" in fails(server, "item_save", repo=PROJECT,
                                   items=[{"key": "rule/x", **RULE, "title": "x", "scope": "x"}])


def test_sem_conexao_diz_como_criar(_isolated_home):
    m = FastMCP(name="t")
    tools.register(m)
    for tool, args in [("item_search", {"query": "x"}), ("workspace_list", {}),
                       ("tag_list", {})]:
        assert "connection_create" in fails(m, tool, **args), tool
