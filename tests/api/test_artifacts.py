def _upload(client, item_id, name="a.txt", data=b"hello", ctype="text/plain"):
    return client.post("/api/artifacts", params={"item_id": item_id},
                       files={"file": (name, data, ctype)})


def test_upload_download_roundtrip(client, mk):
    _, _, it = mk.tree()
    r = _upload(client, it["id"])
    assert r.status_code == 201
    d = r.json()
    assert d["filename"] == "a.txt" and d["file_size"] == 5 and d["item_id"] == it["id"]
    assert "file_path" not in d
    r = client.get(f"/api/artifacts/{d['id']}")
    assert r.status_code == 200
    assert r.content == b"hello"
    assert "a.txt" in r.headers["content-disposition"]


def test_upload_unknown_item_is_404(client):
    assert _upload(client, "nope").status_code == 404


def test_upload_filename_is_sanitized(client, mk):
    _, _, it = mk.tree()
    r = _upload(client, it["id"], name="../../evil.txt")
    assert r.status_code == 201
    assert r.json()["filename"] == "evil.txt"


def test_upload_requires_item_id(client):
    r = client.post("/api/artifacts", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 422


def test_list_with_filter(client, mk):
    ws, dm, a = mk.tree()
    b = mk.item(ws["id"], dm["id"], "B")
    _upload(client, a["id"], "1.txt")
    _upload(client, b["id"], "2.txt")
    assert len(client.get("/api/artifacts").json()) == 2
    r = client.get("/api/artifacts", params={"item_id": a["id"]})
    assert [x["filename"] for x in r.json()] == ["1.txt"]


def test_list_unknown_item_is_404(client):
    assert client.get("/api/artifacts", params={"item_id": "nope"}).status_code == 404


def test_download_missing_is_404(client):
    assert client.get("/api/artifacts/nope").status_code == 404


def test_delete_removes_record_and_file(client, mk, tmp_path):
    _, _, it = mk.tree()
    aid = _upload(client, it["id"]).json()["id"]
    assert len(list((tmp_path / "artifacts").iterdir())) == 1
    assert client.delete(f"/api/artifacts/{aid}").status_code == 204
    assert client.get(f"/api/artifacts/{aid}").status_code == 404
    assert list((tmp_path / "artifacts").iterdir()) == []


def test_delete_missing_is_404(client):
    assert client.delete("/api/artifacts/nope").status_code == 404
