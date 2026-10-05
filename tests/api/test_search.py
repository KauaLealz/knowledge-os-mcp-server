def test_search_finds_item(client, mk):
    ws, _, it = mk.tree()
    r = client.get("/api/items/search", params={"query": "conditional", "workspace_id": ws["id"]})
    assert r.status_code == 200
    d = r.json()
    assert d["query"] == "conditional" and d["total"] == 1
    assert d["results"][0]["id"] == it["id"]
    assert "content" not in d["results"][0]


def test_search_domain_filter(client, mk):
    ws, _, _ = mk.tree()
    dm2 = mk.domain(ws["id"], "D2")
    r = client.get("/api/items/search",
                   params={"query": "conditional", "workspace_id": ws["id"],
                           "domain_id": dm2["id"]})
    assert r.json()["total"] == 0


def test_search_no_match(client, mk):
    ws, _, _ = mk.tree()
    r = client.get("/api/items/search", params={"query": "zzzz", "workspace_id": ws["id"]})
    assert r.json() == {"query": "zzzz", "total": 0, "results": []}


def test_search_requires_workspace(client):
    assert client.get("/api/items/search", params={"query": "x"}).status_code == 422


def test_search_unknown_workspace_is_404(client):
    r = client.get("/api/items/search", params={"query": "x", "workspace_id": "nope"})
    assert r.status_code == 404
