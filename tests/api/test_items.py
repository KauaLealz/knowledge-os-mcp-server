def test_list_empty(client, auth):
    assert client.get("/api/items", headers=auth).json() == []


def test_create_returns_full_item(client, auth, mk):
    ws = mk.ws()
    dm = mk.domain(ws["id"])
    r = client.post("/api/items", headers=auth, json={
        "workspace_id": ws["id"], "domain_id": dm["id"], "type": "knowledge",
        "memory_class": "longterm", "title": "T", "summary": "S", "content": "C",
        "confidence": 90, "importance": 8, "tags": ["spring"], "labels": ["official"],
    })
    assert r.status_code == 201
    d = r.json()
    assert d["tags"] == ["spring"] and d["labels"] == ["official"]
    assert d["confidence"] == 90 and d["access_count"] == 0


def test_create_invalid_type_is_422(client, auth, mk):
    ws = mk.ws()
    dm = mk.domain(ws["id"])
    r = client.post("/api/items", headers=auth, json={
        "workspace_id": ws["id"], "domain_id": dm["id"], "type": "bogus",
        "memory_class": "longterm", "title": "T", "summary": "S", "content": "C"})
    assert r.status_code == 422


def test_create_ephemeral_without_ttl_is_422(client, auth, mk):
    ws = mk.ws()
    dm = mk.domain(ws["id"])
    r = client.post("/api/items", headers=auth, json={
        "workspace_id": ws["id"], "domain_id": dm["id"], "type": "context",
        "memory_class": "ephemeral", "title": "T", "summary": "S", "content": "C"})
    assert r.status_code == 422


def test_create_unknown_workspace_is_404(client, auth):
    r = client.post("/api/items", headers=auth, json={
        "workspace_id": "x", "domain_id": "y", "type": "context", "memory_class": "working",
        "title": "T", "summary": "S", "content": "C"})
    assert r.status_code == 404


def test_get(client, auth, mk):
    _, _, it = mk.tree()
    r = client.get(f"/api/items/{it['id']}", headers=auth)
    assert r.status_code == 200
    assert r.json()["title"] == "Item"


def test_get_missing_is_404(client, auth):
    assert client.get("/api/items/nope", headers=auth).status_code == 404


def test_list_filters(client, auth, mk):
    ws, dm, _ = mk.tree()
    dm2 = mk.domain(ws["id"], "Dom2")
    mk.item(ws["id"], dm2["id"], "Other", type="rule")
    assert len(client.get("/api/items", headers=auth).json()) == 2
    r = client.get("/api/items", params={"domain_id": dm2["id"]}, headers=auth)
    assert [i["title"] for i in r.json()] == ["Other"]
    r = client.get("/api/items", params={"workspace_id": ws["id"], "type": "rule"}, headers=auth)
    assert len(r.json()) == 1
    r = client.get("/api/items", params={"workspace_id": "nope"}, headers=auth)
    assert r.json() == []


def test_list_limit_offset(client, auth, mk):
    ws, dm, _ = mk.tree()
    mk.item(ws["id"], dm["id"], "B")
    mk.item(ws["id"], dm["id"], "C")
    assert len(client.get("/api/items", params={"limit": 2}, headers=auth).json()) == 2
    assert len(client.get("/api/items", params={"limit": 2, "offset": 2}, headers=auth).json()) == 1


def test_update(client, auth, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}", json={"summary": "Novo", "importance": 3},
        headers=auth)
    assert r.status_code == 200
    assert r.json()["summary"] == "Novo" and r.json()["importance"] == 3
    assert r.json()["content"] == "Conteudo Item"


def test_update_invalid_is_422(client, auth, mk):
    _, _, it = mk.tree()
    assert client.put(f"/api/items/{it['id']}", json={"confidence": 500},
                      headers=auth).status_code == 422


def test_update_missing_is_404(client, auth):
    assert client.put("/api/items/nope", json={"summary": "x"}, headers=auth).status_code == 404


def test_delete(client, auth, mk):
    _, _, it = mk.tree()
    assert client.delete(f"/api/items/{it['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/items/{it['id']}", headers=auth).status_code == 404


def test_delete_missing_is_404(client, auth):
    assert client.delete("/api/items/nope", headers=auth).status_code == 404


def test_set_confidence(client, auth, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/confidence", json={"value": 42}, headers=auth)
    assert r.status_code == 200 and r.json()["confidence"] == 42


def test_set_confidence_out_of_range_is_422(client, auth, mk):
    _, _, it = mk.tree()
    assert client.put(f"/api/items/{it['id']}/confidence", json={"value": 101},
                      headers=auth).status_code == 422


def test_set_importance(client, auth, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/importance", json={"value": 9}, headers=auth)
    assert r.status_code == 200 and r.json()["importance"] == 9
    assert client.put(f"/api/items/{it['id']}/importance", json={"value": 11},
                      headers=auth).status_code == 422


def test_set_memory_class_promotes(client, auth, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/memory_class", json={"memory_class": "canonical"},
                   headers=auth)
    assert r.status_code == 200 and r.json()["memory_class"] == "canonical"


def test_set_memory_class_downgrade_is_422(client, auth, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/memory_class", json={"memory_class": "working"},
                   headers=auth)
    assert r.status_code == 422


def test_set_memory_class_missing_item_is_404(client, auth):
    r = client.put("/api/items/nope/memory_class", json={"memory_class": "canonical"}, headers=auth)
    assert r.status_code == 404
