"""Workspaces pela API (v2): listas por `rows()` com `scope` (o que vale) e `scope_explicit`,
contagens, árvore e o grafo do escopo no formato de nó/aresta do `item_graph`."""

ROW_FIELDS = {"id", "name", "description", "scope", "scope_explicit", "items", "projects"}


def _rel(client, a, b, t="related_to"):
    r = client.post("/api/relations",
                    json={"items": [{"source": a["id"], "type": t, "target": b["id"]}]})
    assert r.status_code == 201, r.text


def test_list_empty(client):
    r = client.get("/api/workspaces")
    assert r.status_code == 200 and r.json() == []


def test_create_and_get_com_scope(client):
    r = client.post("/api/workspaces",
                    json={"name": "Test WS", "description": "Test", "scope": "global"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert set(data) == ROW_FIELDS
    assert (data["name"], data["scope"], data["scope_explicit"]) == ("Test WS", "global", "global")
    r = client.get(f"/api/workspaces/{data['id']}")
    assert r.status_code == 200 and r.json()["description"] == "Test"
    assert len(client.get("/api/workspaces").json()) == 1


def test_sem_scope_vale_scoped_sem_explicito(client, mk):
    ws = mk.ws("Plain")
    assert (ws["scope"], ws["scope_explicit"]) == ("scoped", None)


def test_scope_invalido_lista_os_validos(client):
    r = client.post("/api/workspaces", json={"name": "X", "scope": "everyone"})
    assert r.status_code == 422 and "scoped, workspace, global" in r.json()["detail"]


def test_create_duplicate_is_422(client, mk):
    mk.ws("Dup")
    assert client.post("/api/workspaces", json={"name": "Dup"}).status_code == 422


def test_create_empty_name_is_422(client):
    assert client.post("/api/workspaces", json={"name": ""}).status_code == 422


def test_get_missing_is_404(client):
    assert client.get("/api/workspaces/nope").status_code == 404


def test_update_nome_descricao_e_scope(client, mk):
    ws = mk.ws("Old")
    r = client.put(f"/api/workspaces/{ws['id']}", json={"name": "New", "description": "Upd"})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["description"]) == ("New", "Upd")
    r = client.put("/api/workspaces/new", json={"scope": "workspace"})
    assert r.status_code == 200 and r.json()["scope"] == "workspace"
    assert r.json()["name"] == "New"
    r = client.put("/api/workspaces/new", json={"scope": ""})
    assert r.json()["scope_explicit"] is None and r.json()["scope"] == "scoped"


def test_scope_do_workspace_muda_o_alcance_do_que_herda(client, mk):
    ws, dm, it = mk.tree()
    assert it["effective_scope"] == "scoped"
    client.put(f"/api/workspaces/{ws['id']}", json={"scope": "global"})
    got = client.get(f"/api/items/{it['id']}").json()
    assert (got["effective_scope"], got["scope_inherited_from"]) == ("global", "workspace")


def test_update_missing_is_404(client):
    assert client.put("/api/workspaces/nope", json={"name": "x"}).status_code == 404


def test_update_to_existing_name_is_422(client, mk):
    mk.ws("A")
    b = mk.ws("B")
    assert client.put(f"/api/workspaces/{b['id']}", json={"name": "A"}).status_code == 422


def test_delete(client, mk):
    ws = mk.ws("ToDelete")
    assert client.delete(f"/api/workspaces/{ws['id']}").status_code == 204
    assert client.get(f"/api/workspaces/{ws['id']}").status_code == 404


def test_delete_missing_is_404(client):
    assert client.delete("/api/workspaces/nope").status_code == 404


def test_contagens_na_lista(client, mk):
    ws, _, _ = mk.tree()
    mk.project(ws["id"], "Dom2")
    (row,) = client.get("/api/workspaces").json()
    assert (row["projects"], row["items"]) == (2, 1)


def test_tree_v2(client, mk):
    ws = mk.ws("Tree")
    zeta = mk.project(ws["id"], "Zeta", scope="workspace")
    alfa = mk.project(ws["id"], "Alfa")
    mk.project(ws["id"], "Vazio")
    mk.item(ws["id"], zeta["id"], "B item")
    mk.item(ws["id"], zeta["id"], "A item", type="howto", subtype="procedure", status="review")
    mk.item(ws["id"], alfa["id"], "Solo")
    r = client.get(f"/api/workspaces/{ws['id']}/tree")
    assert r.status_code == 200
    projects = r.json()["projects"]
    assert [d["name"] for d in projects] == ["Alfa", "Vazio", "Zeta"]
    assert [d["item_count"] for d in projects] == [1, 0, 2]
    assert (projects[2]["scope"], projects[2]["scope_explicit"]) == ("workspace", "workspace")
    zeta_items = projects[2]["items"]
    assert [i["title"] for i in zeta_items] == ["A item", "B item"]
    assert set(zeta_items[0]) == {"id", "key", "title", "type", "subtype", "status", "scope",
                                  "updated_at", "expired"}
    assert zeta_items[0]["expired"] is False and zeta_items[0]["updated_at"].endswith("Z")
    assert (zeta_items[0]["subtype"], zeta_items[0]["status"]) == ("procedure", "review")
    assert zeta_items[0]["scope"] == "workspace"
    assert projects[1]["items"] == []


def test_tree_missing_is_404(client):
    assert client.get("/api/workspaces/nope/tree").status_code == 404


def test_tree_agrupa_items_por_subject(client, mk):
    ws = mk.ws("ComAssunto")
    p = mk.project(ws["id"], "P")
    bug = mk.subject(ws["id"], p["id"], "Bugs", scope="global")
    mk.subject(ws["id"], p["id"], "Vazio")
    mk.item(ws["id"], p["id"], "Com assunto", subject_id=bug["id"])
    mk.item(ws["id"], p["id"], "Sem assunto")
    project = client.get(f"/api/workspaces/{ws['id']}/tree").json()["projects"][0]
    assert [i["title"] for i in project["items"]] == ["Sem assunto"]
    subj = {s["name"]: s for s in project["subjects"]}
    assert [s["name"] for s in project["subjects"]] == ["Bugs", "Vazio"]
    assert [i["title"] for i in subj["Bugs"]["items"]] == ["Com assunto"]
    assert subj["Bugs"]["items"][0]["scope"] == "global"
    assert (subj["Bugs"]["scope"], subj["Bugs"]["item_count"]) == ("global", 1)
    assert (subj["Vazio"]["items"], subj["Vazio"]["scope_explicit"]) == ([], None)
    assert project["item_count"] == 2


def test_graph_do_workspace(client, mk):
    ws = mk.ws("Graph")
    p = mk.project(ws["id"], "P")
    a = mk.item(ws["id"], p["id"], "A", key="rule/a")
    b = mk.item(ws["id"], p["id"], "B")
    c = mk.item(ws["id"], p["id"], "C")  # sem relação: ainda aparece como nó
    _rel(client, a, b, "supersedes")
    data = client.get(f"/api/workspaces/{ws['id']}/graph").json()
    assert {n["id"] for n in data["nodes"]} == {a["id"], b["id"], c["id"]}
    node_a = next(n for n in data["nodes"] if n["id"] == a["id"])
    assert {"key", "id", "type", "subtype", "title", "summary", "scope", "status"} <= set(node_a)
    assert {"project_id", "project_name", "subject_id", "subject_name"} <= set(node_a)
    assert node_a["project_name"] == "P" and node_a["key"] == "rule/a"
    assert data["edges"] == [{"from": a["id"], "type": "supersedes", "to": b["id"]}]


def test_graph_missing_is_404(client):
    assert client.get("/api/workspaces/nope/graph").status_code == 404


def test_graph_filtra_por_project_e_subject(client, mk):
    ws = mk.ws("Escopos")
    p1 = mk.project(ws["id"], "P1")
    p2 = mk.project(ws["id"], "P2")
    sj = mk.subject(ws["id"], p1["id"], "Assunto")
    a = mk.item(ws["id"], p1["id"], "A", subject_id=sj["id"])
    b = mk.item(ws["id"], p1["id"], "B", subject_id=sj["id"])
    c = mk.item(ws["id"], p1["id"], "C")
    d = mk.item(ws["id"], p2["id"], "D")
    for tgt in (b, c, d):
        _rel(client, a, tgt)
    url = f"/api/workspaces/{ws['id']}/graph"
    by_project = client.get(url, params={"project_id": p1["id"]}).json()
    assert {n["id"] for n in by_project["nodes"]} == {a["id"], b["id"], c["id"]}
    assert len(by_project["edges"]) == 2
    by_subject = client.get(url, params={"project_id": p1["id"], "subject_id": sj["id"]}).json()
    assert {n["id"] for n in by_subject["nodes"]} == {a["id"], b["id"]}
    assert len(by_subject["edges"]) == 1


def test_graph_ignora_relacao_para_fora_do_workspace(client, mk):
    ws1, p1, item1 = mk.tree()
    ws2 = mk.ws("Other")
    item2 = mk.item(ws2["id"], mk.project(ws2["id"], "P2")["id"], "Other item")
    _rel(client, item1, item2)
    assert client.get(f"/api/workspaces/{ws1['id']}/graph").json()["edges"] == []


def test_tree_marca_item_vencido(client, mk, monkeypatch):
    from datetime import timedelta

    from knowledge_os.services import brain

    ws = mk.ws("Venc")
    pj = mk.project(ws["id"], "P")
    mk.item(ws["id"], pj["id"], "Efemero", ttl_days=1)
    mk.item(ws["id"], pj["id"], "Eterno")
    real = brain.utcnow
    monkeypatch.setattr(brain, "utcnow", lambda: real() + timedelta(days=5))
    items = client.get(f"/api/workspaces/{ws['id']}/tree").json()["projects"][0]["items"]
    assert {i["title"]: i["expired"] for i in items} == {"Efemero": True, "Eterno": False}
