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
    r = client.post("/api/workspaces/import",
                    files={"file": ("ws.zip", zip_bytes, "application/zip")})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "WS"
    new_id = r.json()["id"]
    assert client.get(f"/api/workspaces/{new_id}/stats").json()["items"] == 1


def test_export_missing_is_404(client):
    assert client.post("/api/workspaces/nope/export").status_code == 404


def test_import_invalid_zip_is_422(client):
    r = client.post("/api/workspaces/import",
                    files={"file": ("x.zip", b"not a zip", "application/zip")})
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
    assert set(zeta_items[0]) == {
        "id", "title", "type", "memory_class", "confidence", "updated_at"
    }
    assert zeta_items[0]["confidence"] == 40
    assert projects[1]["items"] == []


def test_tree_missing_is_404(client):
    assert client.get("/api/workspaces/nope/tree").status_code == 404
