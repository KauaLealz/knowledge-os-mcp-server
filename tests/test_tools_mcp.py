"""Ferramentas MCP v2 ponta a ponta, pelo protocolo (cliente em memória): as 32 de `tools.py`
(V2_MVP.md §11), cada uma orquestrando o serviço dela."""

import asyncio
import json
import subprocess
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from knowledge_os.mcp import tools

PROJECT = "github.com/org/app"
OTHER = "github.com/org/outro"
ELSE = "github.com/x/e"
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
        return []  # ferramentas com retorno `Any` não estruturam uma lista vazia
    return json.loads(result.content[0].text)


def fails(server: FastMCP, tool: str, /, **args: Any) -> str:
    with pytest.raises(ToolError) as exc:
        call(server, tool, **args)
    return str(exc.value)


def link(server: FastMCP, repo: str, workspace: str, project: str) -> None:
    call(server, "repo", action="link", repo=repo, workspace=workspace, project=project)


@pytest.fixture
def chain(server):
    """W/app (o repositório), W/outro (scope workspace) e E/e (um global e um scoped)."""
    link(server, PROJECT, "W", "app")
    link(server, OTHER, "W", "outro")
    link(server, ELSE, "E", "e")
    call(server, "item_save", repo=PROJECT, items=[
        {"key": "rule/money", **RULE, "title": "Money em pagamentos",
         "scope_paths": ["src/payments/**"], "content": "Use Money, nunca double."}])
    call(server, "item_save", repo=OTHER, items=[
        {"key": "rule/ws-wide", **RULE, "title": "Regra do workspace pagamentos",
         "scope": "workspace"}])
    call(server, "item_save", repo=ELSE, items=[
        {"key": "rule/global-e", **RULE, "title": "Regra global pagamentos", "scope": "global"},
        {"key": "rule/so-e", **RULE, "title": "Regra só de E pagamentos"}])
    return server


# ---- item_save / item_get / item_search ---------------------------------------------------


def test_item_get_resolve_keys_pela_cadeia(chain):
    got = call(chain, "item_get", keys=["rule/money", "rule/ws-wide", "rule/global-e",
                                         "rule/so-e"], repo=PROJECT)
    assert [g.get("where") for g in got[:3]] == ["W/app", "W/outro", "E/e"]
    assert got[0]["content"] == "Use Money, nunca double." and got[2]["scope"] == "global"
    assert got[3] == {"key": "rule/so-e", "missing": True}
    # Sem repo: só os globais pela key; o resto por workspace+project ou id.
    assert call(chain, "item_get", keys=["rule/global-e"])[0]["where"] == "E/e"
    assert call(chain, "item_get", keys=["rule/so-e"], workspace="E", project="e")[0]["title"]
    assert call(chain, "item_get", ids=[got[0]["id"]])[0]["key"] == "rule/money"


def test_item_save_upsert_por_key_e_lote_de_21(chain):
    (before,) = call(chain, "item_get", keys=["rule/money"], repo=PROJECT)
    (row,) = call(chain, "item_save", repo=PROJECT,
                  items=[{"key": "rule/money", "summary": "Valores sempre em Money"}])
    assert row["action"] == "updated" and row["id"] == before["id"]
    assert row["scope"] == "scoped" and row["warnings"] == []
    assert call(chain, "item_save", repo=PROJECT, items=[
        {"key": "rule/money", "summary": "Valores sempre em Money"}])[0]["action"] == "unchanged"
    many = [{"key": f"rule/r{i}", **RULE, "title": f"R{i}"} for i in range(21)]
    assert "no máximo 20" in fails(chain, "item_save", repo=PROJECT, items=many)
    assert "no máximo 20" in fails(chain, "item_get", keys=[f"rule/r{i}" for i in range(21)],
                                   repo=PROJECT)


def test_item_save_avisa_modelo_do_content_e_tag_nova(server):
    link(server, PROJECT, "W", "app")
    (row,) = call(server, "item_save", repo=PROJECT, items=[
        {"key": "rule/pix", "type": "rule", "subtype": "decision", "title": "Pix vencido",
         "summary": "Recusar", "content": "Recusar.", "tags": ["pix"]}])
    text = " ".join(row["warnings"])
    assert "## Por quê" in text and "pix" in text


def test_item_search_cadeia_de_alcance(chain):
    found = call(chain, "item_search", query="pagamentos", repo=PROJECT)
    by_key = {r["key"]: r for r in found["results"]}
    assert set(by_key) == {"rule/money", "rule/ws-wide", "rule/global-e"}
    assert by_key["rule/money"]["where"] == "W/app" and "content" not in by_key["rule/money"]
    assert by_key["rule/global-e"]["where"] == "E/e"
    assert found["results"][0]["key"] == "rule/money"  # mesmo project pesa mais
    everything = call(chain, "item_search", query="pagamentos", everywhere=True)
    assert "rule/so-e" in {r["key"] for r in everything["results"]}
    whole = call(chain, "item_search", query="pagamentos", workspace="E")
    assert {r["key"] for r in whole["results"]} == {"rule/global-e", "rule/so-e"}
    globals_ = call(chain, "item_search", scope=["global"], repo=PROJECT, query="regra")
    assert {r["key"] for r in globals_["results"]} == {"rule/global-e"}


def test_item_search_queries_em_lote_e_paths(chain):
    out = call(chain, "item_search", queries=["money", "global"], repo=PROJECT)
    assert [g["query"] for g in out["groups"]] == ["money", "global"]
    assert out["groups"][1]["results"][0]["key"] == "rule/global-e"
    assert "no máximo 5" in fails(chain, "item_search", queries=list("abcdef"), repo=PROJECT)
    (hit, *_) = call(chain, "item_search", query="money", repo=PROJECT,
                     paths=["src/payments/Charge.java"])["results"]
    assert hit["key"] == "rule/money" and "path" in hit["matched_in"]
    assert hit["excerpt"].startswith("Use Money") and hit["scope_paths"] == ["src/payments/**"]


def test_item_search_sem_consulta_traz_o_essencial(chain):
    out = call(chain, "item_search", repo=PROJECT)
    assert [g["group"] for g in out["groups"]] == ["seguranca", "regras", "contexto", "specs"]
    assert "rule/money" in {r["key"] for g in out["groups"] for r in g["results"]}


def test_item_search_pasta_nao_ligada_so_globais_com_sugestao(chain):
    out = call(chain, "item_search", query="pagamentos")
    assert {r["key"] for r in out["results"]} == {"rule/global-e"}
    assert 'repo(action="link"' in out["suggestion"]


def test_item_search_repo_nao_ligado_vale_como_sem_repo(chain):
    out = call(chain, "item_search", query="pagamentos", repo="path:/tmp/ai8-repo-x")
    assert {r["key"] for r in out["results"]} == {"rule/global-e"}
    assert 'repo="path:/tmp/ai8-repo-x"' in out["suggestion"]
    assert 'repo(action="link"' in out["suggestion"]
    # as outras ferramentas continuam dando erro com a chamada que resolve
    msg = fails(chain, "item_save", repo="path:/tmp/ai8-repo-x", items=[{"key": "rule/a", **RULE}])
    assert "não ligado" in msg and 'repo(action="link"' in msg


def test_item_search_sem_repo_usa_a_pasta_ligada(chain, monkeypatch):
    from knowledge_os.services.repo_service import RepoService

    real = RepoService.resolve
    monkeypatch.setattr(RepoService, "resolve",
                        lambda self, p: real(self, PROJECT if p == "." else p))
    out = call(chain, "item_search", query="pagamentos")
    assert "rule/money" in {r["key"] for r in out["results"]} and "suggestion" not in out


# ---- item_feedback / item_delete ----------------------------------------------------------


def test_item_feedback(chain, tmp_path):
    out = call(chain, "item_feedback", repo=PROJECT, items=[
        {"key": "rule/money", "outcome": "helped"},
        {"key": "rule/ws-wide", "outcome": "wrong", "note": "mudou em 2026"},
        {"key": "rule/nao-existe", "outcome": "helped"}])
    assert out == {"applied": 2, "missing": ["rule/nao-existe"]}
    (wrong,) = call(chain, "item_get", keys=["rule/ws-wide"], repo=PROJECT)
    assert wrong["status"] == "review" and "mudou em 2026" in wrong["content"]
    assert "Válidos: helped" in fails(chain, "item_feedback", repo=PROJECT,
                                      items=[{"key": "rule/money", "outcome": "ok"}])

    # verified com o repo numa pasta git: grava o HEAD dela.
    repo_dir = tmp_path / "codigo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "-c", "user.email=a@b", "-c", "user.name=a",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    head = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    link(chain, str(repo_dir), "W", "app")
    assert call(chain, "item_feedback", repo=str(repo_dir), items=[
        {"key": "rule/money", "outcome": "verified"}])["applied"] == 1
    (verified,) = call(chain, "item_get", keys=["rule/money"], repo=PROJECT)
    assert verified["verified_commit"] == head and verified["verified_at"]


def test_item_delete_candidatos_previa_e_confirm(chain):
    call(chain, "item_save", repo=PROJECT, items=[
        {"key": "rule/velha", **RULE, "title": "Velha", "status": "archived"},
        {"key": "rule/aponta", **RULE, "title": "Aponta"}])
    call(chain, "relation_create", repo=PROJECT, items=[
        {"source": "rule/aponta", "type": "references", "target": "rule/velha"}])
    assert "candidates" in call(chain, "item_delete", repo=PROJECT)
    preview = call(chain, "item_delete", repo=PROJECT, keys=["rule/velha"])
    assert preview["status"] == "preview" and preview["items"][0]["relations_in"] == 1
    assert call(chain, "item_get", keys=["rule/velha"], repo=PROJECT)[0]["title"] == "Velha"
    gone = call(chain, "item_delete", repo=PROJECT, keys=["rule/velha"], confirm=True)
    assert gone["status"] == "deleted" and len(gone["ids"]) == 1
    assert call(chain, "item_get", keys=["rule/velha"], repo=PROJECT)[0]["missing"] is True
    (aponta,) = call(chain, "item_get", keys=["rule/aponta"], repo=PROJECT)
    assert aponta["relations"] == []


# ---- relações e grafo --------------------------------------------------------------------


def test_relation_create_delete_e_item_graph(chain):
    rel = {"source": "rule/money", "type": "depends_on", "target": "rule/global-e"}
    assert call(chain, "relation_create", repo=PROJECT, items=[rel])[0]["action"] == "created"
    assert call(chain, "relation_create", repo=PROJECT, items=[rel])[0]["action"] == "unchanged"
    graph = call(chain, "item_graph", keys=["rule/money"], repo=PROJECT)
    assert {n["key"]: n["hop"] for n in graph["nodes"]} == {"rule/money": 0, "rule/global-e": 1}
    assert graph["edges"] == [{"from": "rule/money", "type": "depends_on",
                               "to": "rule/global-e"}]
    assert graph["truncated"] is False
    only_in = call(chain, "item_graph", keys=["rule/money"], repo=PROJECT, direction="in")
    assert [n["key"] for n in only_in["nodes"]] == ["rule/money"]
    assert call(chain, "relation_delete", repo=PROJECT, items=[rel])[0]["action"] == "deleted"
    assert call(chain, "item_graph", keys=["rule/money"], repo=PROJECT)["edges"] == []
    msg = fails(chain, "relation_create", repo=PROJECT, items=[{**rel, "type": "usa"}])
    assert "related_to" in msg and "supersedes" in msg
    assert "no máximo 5" in fails(chain, "item_graph", keys=list("abcdef"), repo=PROJECT)


def test_supersedes_arquiva_o_alvo(chain):
    call(chain, "relation_create", repo=PROJECT, items=[
        {"source": "rule/money", "type": "supersedes", "target": "rule/ws-wide"}])
    (old,) = call(chain, "item_get", keys=["rule/ws-wide"], repo=PROJECT)
    assert old["status"] == "archived"


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
    assert call(server, "item_get", keys=["rule/a"], repo=PROJECT)[0]["tags"] == [
        "pagamento-pix"]
    preview = call(server, "tag_delete", names=["pagamento-pix"])
    assert preview == {"status": "preview", "tags": [{"name": "pagamento-pix", "items": 1}]}
    assert call(server, "tag_delete", names=["pagamento-pix"], confirm=True)["status"] == "deleted"
    assert call(server, "tag_list") == [{"name": "lgpd", "count": 0}]
    assert "lgpd" in fails(server, "tag_delete", names=["nao-existe"])


# ---- organização --------------------------------------------------------------------------


def test_workspace_crud_com_scope_e_previa(server):
    ws = call(server, "workspace_create", name="Polara", description="cliente", scope="global")
    assert (ws["name"], ws["description"], ws["scope"]) == ("Polara", "cliente", "global")
    call(server, "workspace_create", name="Velho")
    rows = call(server, "workspace_list")
    assert [(r["name"], r["scope"]) for r in rows] == [("Polara", "global"), ("Velho", "scoped")]
    up = call(server, "workspace_update", name="Velho", new_name="Antigo", scope="workspace")
    assert (up["name"], up["scope"]) == ("Antigo", "workspace")
    call(server, "item_save", items=[
        {"workspace": "Antigo", "project": "p", "key": "rule/a", **RULE, "title": "A"}])
    preview = call(server, "workspace_delete", name="Antigo")
    assert preview == {"status": "preview",
                       "would_delete": {"workspace": "Antigo", "projects": 1, "items": 1}}
    assert len(call(server, "workspace_list")) == 2  # nada apagado sem confirm
    assert call(server, "workspace_merge", source="Antigo", target="Polara") == {
        "merged_projects": 1, "renamed_collisions": 0,
        "scope_changes": {"items": 1}}
    done = call(server, "workspace_delete", name="Polara", confirm=True)
    assert done["status"] == "deleted" and done["items"] == 1
    assert call(server, "workspace_list") == []


def test_project_e_subject_crud_com_scope(server):
    call(server, "workspace_create", name="W")
    pj = call(server, "project_create", workspace="W", name="app", scope="workspace")
    assert (pj["name"], pj["scope"]) == ("app", "workspace")
    call(server, "project_create", workspace="W", name="app-old")
    up = call(server, "project_update", workspace="W", name="app-old", description="legado")
    assert up["description"] == "legado"
    sj = call(server, "subject_create", workspace="W", project="app", name="pagamentos",
              scope="global")
    assert sj["scope"] == "global"
    call(server, "subject_create", workspace="W", project="app", name="pagto")
    assert call(server, "subject_update", workspace="W", project="app", name="pagto",
                new_name="cobranca")["name"] == "cobranca"
    call(server, "item_save", items=[{"workspace": "W", "project": "app", "subject": "cobranca",
                                      "key": "rule/a", **RULE, "title": "A"}])
    subjects = call(server, "subject_list", workspace="W", project="app")
    assert [(s["name"], s["scope"], s["items"]) for s in subjects] == [
        ("cobranca", "workspace", 1), ("pagamentos", "global", 0)]
    projects = call(server, "project_list", workspace="W")
    assert [(p["name"], p["subjects"]) for p in projects] == [
        ("app", ["cobranca", "pagamentos"]), ("app-old", [])]
    assert call(server, "subject_merge", workspace="W", project="app", source="cobranca",
                target="pagamentos") == {"merged_items": 1, "scope_changes": {"items": 1}}
    preview = call(server, "subject_delete", workspace="W", project="app", name="pagamentos")
    assert preview == {"status": "preview",
                       "would_delete": {"subject": "pagamentos", "items_sem_assunto": 1},
                       "scope_changes": {"items": 0}}
    call(server, "subject_delete", workspace="W", project="app", name="pagamentos", confirm=True)
    (item,) = call(server, "item_get", keys=["rule/a"], workspace="W", project="app")
    assert item["subject"] is None  # o item fica, sem subject
    assert call(server, "project_merge", workspace="W", source="app-old", target="app")
    preview = call(server, "project_delete", workspace="W", name="app")
    assert preview == {"status": "preview",
                       "would_delete": {"workspace": "W", "project": "app", "items": 1}}
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
    assert call(server, "repo", action="list", workspace="ai8") == []
    assert "não ligado" in fails(server, "repo", action="unlink", repo="path:/tmp/ai8-repo-x")
    assert call(server, "repo", action="sync") == {"synced": False}
    assert "link, list, unlink ou sync" in fails(server, "repo", action="rename")


def test_connection_create_list_delete(_isolated_home, tmp_path):
    m = FastMCP(name="t")
    tools.register(m)
    created = call(m, "connection_create", name="Pessoal", path=str(tmp_path / "pasta"))
    assert created["name"] == "Pessoal" and created["is_default"] is True
    assert [c["name"] for c in call(m, "connection_list")] == ["Pessoal"]
    assert call(m, "connection_delete", id=created["id"]) == {"status": "deleted",
                                                             "id": created["id"]}
    assert call(m, "connection_list") == []
    assert (tmp_path / "pasta").is_dir()  # a pasta é do usuário: fica


# ---- health_check -------------------------------------------------------------------------


def test_health_check_com_md_quebrado(server, data_dir):
    call(server, "item_save", items=[
        {"workspace": "W", "project": "p", "key": "rule/a", **RULE, "title": "A"}])
    (data_dir / "w" / "p" / "quebrado.md").write_text("---\nid: [sem fim\n---\n",
                                                       encoding="utf-8")
    report = call(server, "health_check")
    assert set(report) >= {"status", "version", "connections", "gh_authenticated"}
    (conn,) = report["connections"]
    assert conn["name"] == "Teste" and conn["ok"] is True and conn["path"] == str(data_dir)
    assert [e["path"] for e in conn["parse_errors"]] == ["w/p/quebrado.md"]
    assert report["status"] == "ok" and isinstance(report["gh_authenticated"], bool)


def test_health_check_sem_conexao_e_com_cadastro_quebrado(_isolated_home):
    m = FastMCP(name="t")
    tools.register(m)
    report = call(m, "health_check")
    assert report["status"] == "error" and report["connections"] == []
    assert "connection_create" in report["message"] and report["version"]
    _isolated_home.mkdir(parents=True, exist_ok=True)
    (_isolated_home / "connections.json").write_text(json.dumps({
        "version": "1.0", "default": "pg",
        "connections": [{"id": "pg", "name": "PG", "review_mode": "sync"}]}), encoding="utf-8")
    broken = call(m, "health_check")
    assert broken["status"] == "error" and "review_mode" in broken["message"]


# ---- erros que dizem como corrigir --------------------------------------------------------


def test_repo_nao_ligado_diz_a_chamada_que_resolve(server):
    hint = 'repo(action="link", repo="github.com/o/n")'
    entry = {"key": "rule/x", **RULE, "title": "X"}
    assert hint in fails(server, "item_save", repo="github.com/o/n", items=[entry])
    assert hint in fails(server, "item_feedback", repo="github.com/o/n",
                         items=[{"key": "rule/x", "outcome": "helped"}])
    rel = {"source": "rule/x", "type": "related_to", "target": "rule/y"}
    assert hint in fails(server, "relation_create", repo="github.com/o/n", items=[rel])
    assert hint in fails(server, "relation_delete", repo="github.com/o/n", items=[rel])
    # item_search é a exceção: repo não ligado vale como pasta não ligada (globais + sugestão)
    sugestao = call(server, "item_search", repo="github.com/o/n", query="x")["suggestion"]
    assert hint.removesuffix(")") in sugestao
    assert "repo" in fails(server, "item_save", items=[entry])  # sem lugar: pede repo


def test_tipo_e_scope_invalidos_listam_os_validos(server):
    link(server, PROJECT, "W", "app")
    msg = fails(server, "item_save", repo=PROJECT, items=[
        {"key": "rule/ok", **RULE, "title": "ok"},
        {"key": "rule/x", **RULE, "title": "x", "type": "insight"}])
    assert "Entrada 1" in msg and "Válidos: rule, howto, context, spec, secret" in msg
    assert call(server, "item_get", keys=["rule/ok"], repo=PROJECT) == [
        {"key": "rule/ok", "missing": True}]  # o lote foi desfeito
    msg = fails(server, "item_save", repo=PROJECT,
                items=[{"key": "rule/x", **RULE, "title": "x", "scope": "projeto"}])
    assert "Válidos: scoped, workspace, global" in msg
    assert "scoped, workspace, global" in fails(server, "workspace_create", name="X",
                                                scope="projeto")
    assert "labels" in fails(server, "item_save", repo=PROJECT,
                             items=[{"key": "rule/x", **RULE, "title": "x", "labels": ["a"]}])


def test_sem_conexao_diz_como_criar(_isolated_home):
    m = FastMCP(name="t")
    tools.register(m)
    for tool, args in [("item_search", {"query": "x"}), ("workspace_list", {}),
                       ("tag_list", {})]:
        assert "connection_create" in fails(m, tool, **args), tool
