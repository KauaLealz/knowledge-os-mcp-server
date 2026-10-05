BASE = "/api/tags"
ITEM = "/api/items/{id}/tags"


def _create(client, name="custom"):
    return client.post(BASE, json={"name": name})


def test_list_and_create(client):
    before = len(client.get(BASE).json())
    r = _create(client)
    assert r.status_code == 201 and r.json()["name"] == "custom"
    names = [x["name"] for x in client.get(BASE).json()]
    assert len(names) == before + 1 and "custom" in names


def test_create_duplicate_is_422(client):
    _create(client)
    assert _create(client).status_code == 422


def test_create_blank_is_422(client):
    assert client.post(BASE, json={"name": "   "}).status_code == 422


def test_delete(client):
    rid = _create(client).json()["id"]
    assert client.delete(f"{BASE}/{rid}").status_code == 204
    assert "custom" not in [x["name"] for x in client.get(BASE).json()]


def test_delete_missing_is_404(client):
    assert client.delete(f"{BASE}/nope").status_code == 404


def test_item_tags_add_list_remove(client, mk):
    _, _, it = mk.tree()
    url = ITEM.format(id=it["id"])
    assert client.get(url).json() == []
    obj = _create(client).json()
    r = client.post(url, json={"tag_id": obj["id"]})
    assert r.status_code == 201
    assert [x["id"] for x in client.get(url).json()] == [obj["id"]]
    assert client.post(url, json={"tag_id": obj["id"]}).status_code == 201
    assert len(client.get(url).json()) == 1  # idempotente
    assert client.delete(f"{url}/{obj['id']}").status_code == 204
    assert client.get(url).json() == []


def test_item_tags_unknown_item_is_404(client):
    assert client.get(ITEM.format(id="nope")).status_code == 404
    obj = _create(client).json()
    r = client.post(ITEM.format(id="nope"), json={"tag_id": obj["id"]})
    assert r.status_code == 404


def test_item_tags_unknown_tag_is_404(client, mk):
    _, _, it = mk.tree()
    url = ITEM.format(id=it["id"])
    assert client.post(url, json={"tag_id": "nope"}).status_code == 404
    assert client.delete(f"{url}/nope").status_code == 404


def test_item_response_reflects_tags(client, mk):
    _, _, it = mk.tree()
    obj = _create(client, "zeta").json()
    client.post(ITEM.format(id=it["id"]), json={"tag_id": obj["id"]})
    assert "zeta" in client.get(f"/api/items/{it['id']}").json()["tags"]
