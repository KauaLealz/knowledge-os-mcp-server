def test_list_empty(client):
    assert client.get("/api/domains").json() == []


def test_create_get(client, mk):
    ws = mk.ws()
    body = {"workspace_id": ws["id"], "name": "D", "description": "x"}
    r = client.post("/api/domains", json=body)
    assert r.status_code == 201
    d = r.json()
    assert d["workspace_id"] == ws["id"]
    assert client.get(f"/api/domains/{d['id']}").json()["name"] == "D"


def test_create_workspace_missing_is_404(client):
    r = client.post("/api/domains", json={"workspace_id": "nope", "name": "D"})
    assert r.status_code == 404


def test_create_duplicate_is_422(client, mk):
    ws = mk.ws()
    mk.domain(ws["id"], "D")
    r = client.post("/api/domains", json={"workspace_id": ws["id"], "name": "D"})
    assert r.status_code == 422


def test_list_filter_by_workspace(client, mk):
    a, b = mk.ws("A"), mk.ws("B")
    mk.domain(a["id"], "D1")
    mk.domain(b["id"], "D2")
    r = client.get("/api/domains", params={"workspace_id": a["id"]})
    assert [d["name"] for d in r.json()] == ["D1"]
    assert len(client.get("/api/domains").json()) == 2


def test_get_missing_is_404(client):
    assert client.get("/api/domains/nope").status_code == 404


def test_update(client, mk):
    d = mk.domain(mk.ws()["id"], "Old")
    r = client.put(f"/api/domains/{d['id']}", json={"name": "New", "description": "D"})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["description"]) == ("New", "D")


def test_update_missing_is_404(client):
    assert client.put("/api/domains/nope", json={"name": "x"}).status_code == 404


def test_update_duplicate_is_422(client, mk):
    ws = mk.ws()
    mk.domain(ws["id"], "A")
    b = mk.domain(ws["id"], "B")
    assert client.put(f"/api/domains/{b['id']}", json={"name": "A"}).status_code == 422


def test_delete(client, mk):
    d = mk.domain(mk.ws()["id"])
    assert client.delete(f"/api/domains/{d['id']}").status_code == 204
    assert client.get(f"/api/domains/{d['id']}").status_code == 404


def test_delete_missing_is_404(client):
    assert client.delete("/api/domains/nope").status_code == 404


def test_stats(client, mk):
    _, dm, _ = mk.tree()
    r = client.get(f"/api/domains/{dm['id']}/stats")
    assert r.json() == {"items": 1}


def test_stats_missing_is_404(client):
    assert client.get("/api/domains/nope/stats").status_code == 404


def test_export(client, mk):
    _, dm, _ = mk.tree()
    r = client.post(f"/api/domains/{dm['id']}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.content[:2] == b"PK"


def test_export_missing_is_404(client):
    assert client.post("/api/domains/nope/export").status_code == 404
