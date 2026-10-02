def test_list_empty(client, auth):
    r = client.get("/api/workspaces", headers=auth)
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get(client, auth):
    r = client.post("/api/workspaces", json={"name": "Test WS", "description": "Test"},
        headers=auth)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test WS"
    r = client.get(f"/api/workspaces/{data['id']}", headers=auth)
    assert r.status_code == 200
    assert r.json()["description"] == "Test"
    assert len(client.get("/api/workspaces", headers=auth).json()) == 1


def test_create_duplicate_is_422(client, auth, mk):
    mk.ws("Dup")
    r = client.post("/api/workspaces", json={"name": "Dup"}, headers=auth)
    assert r.status_code == 422


def test_create_empty_name_is_422(client, auth):
    assert client.post("/api/workspaces", json={"name": ""}, headers=auth).status_code == 422


def test_get_missing_is_404(client, auth):
    assert client.get("/api/workspaces/nope", headers=auth).status_code == 404


def test_update(client, auth, mk):
    ws = mk.ws("Old")
    r = client.put(f"/api/workspaces/{ws['id']}", json={"name": "New", "description": "Upd"},
                   headers=auth)
    assert r.status_code == 200
    assert r.json()["name"] == "New"
    assert r.json()["description"] == "Upd"


def test_update_missing_is_404(client, auth):
    r = client.put("/api/workspaces/nope", json={"name": "x"}, headers=auth)
    assert r.status_code == 404


def test_update_to_existing_name_is_422(client, auth, mk):
    mk.ws("A")
    b = mk.ws("B")
    r = client.put(f"/api/workspaces/{b['id']}", json={"name": "A"}, headers=auth)
    assert r.status_code == 422


def test_delete(client, auth, mk):
    ws = mk.ws("ToDelete")
    assert client.delete(f"/api/workspaces/{ws['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/workspaces/{ws['id']}", headers=auth).status_code == 404


def test_delete_missing_is_404(client, auth):
    assert client.delete("/api/workspaces/nope", headers=auth).status_code == 404


def test_stats(client, auth, mk):
    ws, dm, _ = mk.tree()
    mk.domain(ws["id"], "Dom2")
    r = client.get(f"/api/workspaces/{ws['id']}/stats", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"domains": 2, "items": 1}


def test_stats_missing_is_404(client, auth):
    assert client.get("/api/workspaces/nope/stats", headers=auth).status_code == 404


def test_export_import_roundtrip(client, auth, mk):
    ws, _, _ = mk.tree()
    r = client.post(f"/api/workspaces/{ws['id']}/export", headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zip_bytes = r.content
    client.delete(f"/api/workspaces/{ws['id']}", headers=auth)
    r = client.post("/api/workspaces/import", headers=auth,
                    files={"file": ("ws.zip", zip_bytes, "application/zip")})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "WS"
    new_id = r.json()["id"]
    assert client.get(f"/api/workspaces/{new_id}/stats", headers=auth).json()["items"] == 1


def test_export_missing_is_404(client, auth):
    assert client.post("/api/workspaces/nope/export", headers=auth).status_code == 404


def test_import_invalid_zip_is_422(client, auth):
    r = client.post("/api/workspaces/import", headers=auth,
                    files={"file": ("x.zip", b"not a zip", "application/zip")})
    assert r.status_code == 422


def test_tree(client, auth, mk):
    ws = mk.ws("Tree")
    zeta = mk.domain(ws["id"], "Zeta")
    alfa = mk.domain(ws["id"], "Alfa")
    mk.domain(ws["id"], "Vazio")
    mk.item(ws["id"], zeta["id"], "B item")
    mk.item(ws["id"], zeta["id"], "A item", confidence=40)
    mk.item(ws["id"], alfa["id"], "Solo")
    r = client.get(f"/api/workspaces/{ws['id']}/tree", headers=auth)
    assert r.status_code == 200
    domains = r.json()["domains"]
    assert [d["name"] for d in domains] == ["Alfa", "Vazio", "Zeta"]
    assert [d["item_count"] for d in domains] == [1, 0, 2]
    zeta_items = domains[2]["items"]
    assert [i["title"] for i in zeta_items] == ["A item", "B item"]
    assert set(zeta_items[0]) == {
        "id", "title", "type", "memory_class", "confidence", "updated_at"
    }
    assert zeta_items[0]["confidence"] == 40
    assert domains[1]["items"] == []


def test_tree_missing_is_404(client, auth):
    assert client.get("/api/workspaces/nope/tree", headers=auth).status_code == 404
