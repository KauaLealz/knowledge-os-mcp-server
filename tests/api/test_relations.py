def _two(mk):
    ws, dm, a = mk.tree()
    b = mk.item(ws["id"], dm["id"], "B")
    return a, b


def _rel(client, auth, a, b, t="related_to"):
    return client.post("/api/relations", headers=auth, json={
        "source_item_id": a["id"], "target_item_id": b["id"], "relation_type": t})


def test_create_and_list(client, auth, mk):
    a, b = _two(mk)
    r = _rel(client, auth, a, b)
    assert r.status_code == 201
    assert r.json()["relation_type"] == "related_to"
    assert len(client.get("/api/relations", headers=auth).json()) == 1


def test_create_invalid_type_is_422(client, auth, mk):
    a, b = _two(mk)
    assert _rel(client, auth, a, b, "bogus").status_code == 422


def test_create_self_relation_is_422(client, auth, mk):
    a, _ = _two(mk)
    assert _rel(client, auth, a, a).status_code == 422


def test_create_missing_item_is_404(client, auth, mk):
    a, _ = _two(mk)
    assert _rel(client, auth, a, {"id": "nope"}).status_code == 404


def test_list_filters(client, auth, mk):
    a, b = _two(mk)
    _rel(client, auth, a, b, "related_to")
    _rel(client, auth, b, a, "depends_on")
    r = client.get("/api/relations", params={"type": "depends_on"}, headers=auth)
    assert len(r.json()) == 1
    r = client.get("/api/relations", params={"item_id": a["id"]}, headers=auth)
    assert len(r.json()) == 2
    r = client.get("/api/relations", params={"item_id": "nope"}, headers=auth)
    assert r.json() == []


def test_item_relations_grouped(client, auth, mk):
    a, b = _two(mk)
    _rel(client, auth, a, b, "related_to")
    _rel(client, auth, b, a, "depends_on")
    r = client.get(f"/api/items/{a['id']}/relations", headers=auth)
    assert r.status_code == 200
    assert set(r.json()) == {"related_to", "depends_on"}
    assert len(r.json()["related_to"]) == 1


def test_item_relations_missing_item_is_404(client, auth):
    assert client.get("/api/items/nope/relations", headers=auth).status_code == 404


def test_delete(client, auth, mk):
    a, b = _two(mk)
    rid = _rel(client, auth, a, b).json()["id"]
    assert client.delete(f"/api/relations/{rid}", headers=auth).status_code == 204
    assert client.get("/api/relations", headers=auth).json() == []


def test_delete_missing_is_404(client, auth):
    assert client.delete("/api/relations/nope", headers=auth).status_code == 404
