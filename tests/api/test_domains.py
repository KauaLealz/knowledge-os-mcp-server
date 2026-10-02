def test_list_empty(client, auth):
    assert client.get("/api/domains", headers=auth).json() == []


def test_create_get(client, auth, mk):
    ws = mk.ws()
    body = {"workspace_id": ws["id"], "name": "D", "description": "x"}
    r = client.post("/api/domains", json=body, headers=auth)
    assert r.status_code == 201
    d = r.json()
    assert d["workspace_id"] == ws["id"]
    assert client.get(f"/api/domains/{d['id']}", headers=auth).json()["name"] == "D"


def test_create_workspace_missing_is_404(client, auth):
    r = client.post("/api/domains", json={"workspace_id": "nope", "name": "D"}, headers=auth)
    assert r.status_code == 404


def test_create_duplicate_is_422(client, auth, mk):
    ws = mk.ws()
    mk.domain(ws["id"], "D")
    r = client.post("/api/domains", json={"workspace_id": ws["id"], "name": "D"}, headers=auth)
    assert r.status_code == 422


def test_list_filter_by_workspace(client, auth, mk):
    a, b = mk.ws("A"), mk.ws("B")
    mk.domain(a["id"], "D1")
    mk.domain(b["id"], "D2")
    r = client.get("/api/domains", params={"workspace_id": a["id"]}, headers=auth)
    assert [d["name"] for d in r.json()] == ["D1"]
    assert len(client.get("/api/domains", headers=auth).json()) == 2


def test_get_missing_is_404(client, auth):
    assert client.get("/api/domains/nope", headers=auth).status_code == 404


def test_update(client, auth, mk):
    d = mk.domain(mk.ws()["id"], "Old")
    r = client.put(f"/api/domains/{d['id']}", json={"name": "New", "description": "D"},
        headers=auth)
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["description"]) == ("New", "D")


def test_update_missing_is_404(client, auth):
    assert client.put("/api/domains/nope", json={"name": "x"}, headers=auth).status_code == 404


def test_update_duplicate_is_422(client, auth, mk):
    ws = mk.ws()
    mk.domain(ws["id"], "A")
    b = mk.domain(ws["id"], "B")
    assert client.put(f"/api/domains/{b['id']}", json={"name": "A"},
        headers=auth).status_code == 422


def test_delete(client, auth, mk):
    d = mk.domain(mk.ws()["id"])
    assert client.delete(f"/api/domains/{d['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/domains/{d['id']}", headers=auth).status_code == 404


def test_delete_missing_is_404(client, auth):
    assert client.delete("/api/domains/nope", headers=auth).status_code == 404


def test_stats(client, auth, mk):
    _, dm, _ = mk.tree()
    r = client.get(f"/api/domains/{dm['id']}/stats", headers=auth)
    assert r.json() == {"items": 1}


def test_stats_missing_is_404(client, auth):
    assert client.get("/api/domains/nope/stats", headers=auth).status_code == 404


def test_export(client, auth, mk):
    _, dm, _ = mk.tree()
    r = client.post(f"/api/domains/{dm['id']}/export", headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.content[:2] == b"PK"


def test_export_missing_is_404(client, auth):
    assert client.post("/api/domains/nope/export", headers=auth).status_code == 404
