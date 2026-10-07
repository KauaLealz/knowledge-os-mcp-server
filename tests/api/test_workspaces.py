def test_list_empty(client):
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get(client):
    r = client.post("/api/workspaces", json={"name": "Test WS", "description": "Test"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test WS"
    r = client.get(f"/api/workspaces/{data['id']}")
    assert r.status_code == 200
    assert r.json()["description"] == "Test"
    assert len(client.get("/api/workspaces").json()) == 1


def test_create_duplicate_is_422(client, mk):
    mk.ws("Dup")
    r = client.post("/api/workspaces", json={"name": "Dup"})
    assert r.status_code == 422


def test_create_empty_name_is_422(client):
    assert client.post("/api/workspaces", json={"name": ""}).status_code == 422


def test_get_missing_is_404(client):
    assert client.get("/api/workspaces/nope").status_code == 404


def test_update(client, mk):
    ws = mk.ws("Old")
    r = client.put(f"/api/workspaces/{ws['id']}", json={"name": "New", "description": "Upd"})
    assert r.status_code == 200
    assert r.json()["name"] == "New"
    assert r.json()["description"] == "Upd"


def test_update_missing_is_404(client):
    r = client.put("/api/workspaces/nope", json={"name": "x"})
    assert r.status_code == 404


def test_update_to_existing_name_is_422(client, mk):
    mk.ws("A")
    b = mk.ws("B")
    r = client.put(f"/api/workspaces/{b['id']}", json={"name": "A"})
    assert r.status_code == 422


def test_delete(client, mk):
    ws = mk.ws("ToDelete")
    assert client.delete(f"/api/workspaces/{ws['id']}").status_code == 204
    assert client.get(f"/api/workspaces/{ws['id']}").status_code == 404


def test_delete_missing_is_404(client):
    assert client.delete("/api/workspaces/nope").status_code == 404


def test_stats(client, mk):
    ws, dm, _ = mk.tree()
    mk.project(ws["id"], "Dom2")
    r = client.get(f"/api/workspaces/{ws['id']}/stats")
    assert r.status_code == 200
    assert r.json() == {"projects": 2, "items": 1}


def test_stats_missing_is_404(client):
    assert client.get("/api/workspaces/nope/stats").status_code == 404


def test_export_import_roundtrip(client, mk):
    ws, _, _ = mk.tree()
    r = client.post(f"/api/workspaces/{ws['id']}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zip_bytes = r.content
    client.delete(f"/api/workspaces/{ws['id']}")
    r = client.post(
        "/api/workspaces/import", files={"file": ("ws.zip", zip_bytes, "application/zip")}
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "WS"
    new_id = r.json()["id"]
    assert client.get(f"/api/workspaces/{new_id}/stats").json()["items"] == 1


def test_export_missing_is_404(client):
    assert client.post("/api/workspaces/nope/export").status_code == 404


def test_import_invalid_zip_is_422(client):
    r = client.post(
        "/api/workspaces/import", files={"file": ("x.zip", b"not a zip", "application/zip")}
    )
    assert r.status_code == 422


def test_tree(client, mk):
    ws = mk.ws("Tree")
    zeta = mk.project(ws["id"], "Zeta")
    alfa = mk.project(ws["id"], "Alfa")
    mk.project(ws["id"], "Vazio")
    mk.item(ws["id"], zeta["id"], "B item")
    mk.item(ws["id"], zeta["id"], "A item", confidence=40)
    mk.item(ws["id"], alfa["id"], "Solo")
    r = client.get(f"/api/workspaces/{ws['id']}/tree")
    assert r.status_code == 200
    projects = r.json()["projects"]
    assert [d["name"] for d in projects] == ["Alfa", "Vazio", "Zeta"]
    assert [d["item_count"] for d in projects] == [1, 0, 2]
    zeta_items = projects[2]["items"]
    assert [i["title"] for i in zeta_items] == ["A item", "B item"]
    assert set(zeta_items[0]) == {"id", "title", "type", "memory_class", "confidence", "updated_at"}
    assert zeta_items[0]["confidence"] == 40
    assert projects[1]["items"] == []


def test_tree_missing_is_404(client):
    assert client.get("/api/workspaces/nope/tree").status_code == 404


def test_tree_agrupa_items_por_subject(client, mk, engine):
    from sqlalchemy.orm import Session

    from knowledge_os.services.subject_service import SubjectService

    ws = mk.ws("ComAssunto")
    p = mk.project(ws["id"], "P")
    with Session(engine) as s:
        subjects = SubjectService(s)
        bug = subjects.create(p["id"], "Bugs")
        subjects.create(p["id"], "Vazio")
        bug_id = bug.id
    mk.item(ws["id"], p["id"], "Com assunto", subject_id=bug_id)
    mk.item(ws["id"], p["id"], "Sem assunto")

    r = client.get(f"/api/workspaces/{ws['id']}/tree")
    assert r.status_code == 200
    project = r.json()["projects"][0]

    assert [i["title"] for i in project["items"]] == ["Sem assunto"]

    subj_by_name = {s["name"]: s for s in project["subjects"]}
    assert set(subj_by_name) == {"Bugs", "Vazio"}
    assert [s["name"] for s in project["subjects"]] == ["Bugs", "Vazio"]

    assert [i["title"] for i in subj_by_name["Bugs"]["items"]] == ["Com assunto"]
    assert subj_by_name["Bugs"]["item_count"] == 1
    assert subj_by_name["Vazio"]["items"] == []
    assert subj_by_name["Vazio"]["item_count"] == 0

    assert project["item_count"] == 2


def test_graph(client, mk):
    ws = mk.ws("Graph")
    p = mk.project(ws["id"], "P")
    a = mk.item(ws["id"], p["id"], "A")
    b = mk.item(ws["id"], p["id"], "B")
    c = mk.item(ws["id"], p["id"], "C")  # sem relação: ainda aparece como nó
    r = client.post(
        "/api/relations",
        json={"source_item_id": a["id"], "target_item_id": b["id"], "relation_type": "supersedes"},
    )
    assert r.status_code == 201, r.text

    resp = client.get(f"/api/workspaces/{ws['id']}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert {n["id"] for n in data["nodes"]} == {a["id"], b["id"], c["id"]}
    node_a = next(n for n in data["nodes"] if n["id"] == a["id"])
    assert set(node_a) == {"id", "title", "type", "project_id", "status"}
    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["source"] == a["id"]
    assert edge["target"] == b["id"]
    assert edge["relation_type"] == "supersedes"


def test_graph_missing_is_404(client):
    assert client.get("/api/workspaces/nope/graph").status_code == 404


def test_graph_ignores_relation_pointing_outside_workspace(client, mk):
    ws1, p1, item1 = mk.tree()
    ws2 = mk.ws("Other")
    p2 = mk.project(ws2["id"], "P2")
    item2 = mk.item(ws2["id"], p2["id"], "Other item")
    r = client.post(
        "/api/relations",
        json={
            "source_item_id": item1["id"],
            "target_item_id": item2["id"],
            "relation_type": "related_to",
        },
    )
    assert r.status_code == 201, r.text

    resp = client.get(f"/api/workspaces/{ws1['id']}/graph")
    assert resp.status_code == 200
    assert resp.json()["edges"] == []
