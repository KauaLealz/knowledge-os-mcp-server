BASE = "/api/tags"
ITEM = "/api/items/{id}/tags"


def _create(client, auth, name="custom"):
    return client.post(BASE, json={"name": name}, headers=auth)


def test_list_and_create(client, auth):
    before = len(client.get(BASE, headers=auth).json())
    r = _create(client, auth)
    assert r.status_code == 201 and r.json()["name"] == "custom"
    names = [x["name"] for x in client.get(BASE, headers=auth).json()]
    assert len(names) == before + 1 and "custom" in names


def test_create_duplicate_is_422(client, auth):
    _create(client, auth)
    assert _create(client, auth).status_code == 422


def test_create_blank_is_422(client, auth):
    assert client.post(BASE, json={"name": "   "}, headers=auth).status_code == 422


def test_delete(client, auth):
    rid = _create(client, auth).json()["id"]
    assert client.delete(f"{BASE}/{rid}", headers=auth).status_code == 204
    assert "custom" not in [x["name"] for x in client.get(BASE, headers=auth).json()]


def test_delete_missing_is_404(client, auth):
    assert client.delete(f"{BASE}/nope", headers=auth).status_code == 404


def test_item_tags_add_list_remove(client, auth, mk):
    _, _, it = mk.tree()
    url = ITEM.format(id=it["id"])
    assert client.get(url, headers=auth).json() == []
    obj = _create(client, auth).json()
    r = client.post(url, json={"tag_id": obj["id"]}, headers=auth)
    assert r.status_code == 201
    assert [x["id"] for x in client.get(url, headers=auth).json()] == [obj["id"]]
    assert client.post(url, json={"tag_id": obj["id"]}, headers=auth).status_code == 201
    assert len(client.get(url, headers=auth).json()) == 1  # idempotente
    assert client.delete(f"{url}/{obj['id']}", headers=auth).status_code == 204
    assert client.get(url, headers=auth).json() == []


def test_item_tags_unknown_item_is_404(client, auth):
    assert client.get(ITEM.format(id="nope"), headers=auth).status_code == 404
    obj = _create(client, auth).json()
    r = client.post(ITEM.format(id="nope"), json={"tag_id": obj["id"]}, headers=auth)
    assert r.status_code == 404


def test_item_tags_unknown_tag_is_404(client, auth, mk):
    _, _, it = mk.tree()
    url = ITEM.format(id=it["id"])
    assert client.post(url, json={"tag_id": "nope"}, headers=auth).status_code == 404
    assert client.delete(f"{url}/nope", headers=auth).status_code == 404


def test_item_response_reflects_tags(client, auth, mk):
    _, _, it = mk.tree()
    obj = _create(client, auth, "zeta").json()
    client.post(ITEM.format(id=it["id"]), json={"tag_id": obj["id"]}, headers=auth)
    assert "zeta" in client.get(f"/api/items/{it['id']}", headers=auth).json()["tags"]
