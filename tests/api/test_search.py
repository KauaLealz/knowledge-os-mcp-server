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


def test_search_without_workspace_searches_everywhere(client, mk):
    ws, _, it = mk.tree()
    ws2 = mk.ws("Outro")
    dm2 = mk.domain(ws2["id"], "D2")
    it2 = mk.item(ws2["id"], dm2["id"], "Segundo")
    r = client.get("/api/items/search", params={"query": "conditional"})
    assert r.status_code == 200
    assert {x["id"] for x in r.json()["results"]} == {it["id"], it2["id"]}


def test_search_results_have_link_fields(client, mk):
    ws, dm, it = mk.tree()
    hit = client.get("/api/items/search", params={"query": "conditional"}).json()["results"][0]
    assert hit["workspace_id"] == ws["id"] and hit["domain_id"] == dm["id"]
    assert hit["type"] == "knowledge"


def test_search_filters_by_types(client, mk):
    ws, dm, it = mk.tree()
    rule = mk.item(ws["id"], dm["id"], "Regra", type="rule")
    def ids(types):
        r = client.get("/api/items/search", params={"query": "conditional", "types": types})
        assert r.status_code == 200
        return {x["id"] for x in r.json()["results"]}
    assert ids("rule") == {rule["id"]}
    assert ids("rule,knowledge") == {rule["id"], it["id"]}


def test_search_invalid_type_is_422(client, mk):
    mk.tree()
    r = client.get("/api/items/search", params={"query": "conditional", "types": "rule,xyz"})
    assert r.status_code == 422


def test_search_limit_up_to_50(client):
    assert client.get("/api/items/search", params={"query": "x", "limit": 50}).status_code == 200
    assert client.get("/api/items/search", params={"query": "x", "limit": 51}).status_code == 422


def test_search_unknown_workspace_is_404(client):
    r = client.get("/api/items/search", params={"query": "x", "workspace_id": "nope"})
    assert r.status_code == 404
