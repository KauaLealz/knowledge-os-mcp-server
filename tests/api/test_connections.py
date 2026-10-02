from sqlalchemy.orm import Session

from src.db.models import Connection


def _create(client, auth, tmp_path, name="extra"):
    return client.post("/api/connections", headers=auth, json={
        "name": name, "db_type": "sqlite", "db_url": f"sqlite:///{tmp_path / (name + '.db')}"})


def test_list_has_default(client, auth):
    r = client.get("/api/connections", headers=auth)
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == ["default"]


def test_create_get(client, auth, tmp_path):
    r = _create(client, auth, tmp_path)
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "extra" and c["db_type"] == "sqlite"
    assert client.get(f"/api/connections/{c['id']}", headers=auth).json()["name"] == "extra"
    assert len(client.get("/api/connections", headers=auth).json()) == 2


def test_create_duplicate_is_422(client, auth, tmp_path):
    _create(client, auth, tmp_path)
    assert _create(client, auth, tmp_path).status_code == 422


def test_create_invalid_type_is_422(client, auth):
    r = client.post("/api/connections", headers=auth,
                    json={"name": "x", "db_type": "oracle", "db_url": "oracle://x"})
    assert r.status_code == 422


def test_create_mismatched_url_is_422(client, auth):
    r = client.post("/api/connections", headers=auth,
                    json={"name": "x", "db_type": "mysql", "db_url": "sqlite:///a.db"})
    assert r.status_code == 422


def test_get_missing_is_404(client, auth):
    assert client.get("/api/connections/nope", headers=auth).status_code == 404


def test_password_never_exposed(client, auth, engine):
    with Session(engine) as s:
        s.add(Connection(id="c1", name="pg", db_type="postgresql",
                         db_url="postgresql://u:secret@h:5432/db"))
        s.commit()
    r = client.get("/api/connections/c1", headers=auth)
    assert r.status_code == 200
    assert "secret" not in r.text
    assert "secret" not in client.get("/api/connections", headers=auth).text


def test_test_endpoint(client, auth, tmp_path):
    cid = _create(client, auth, tmp_path).json()["id"]
    r = client.post(f"/api/connections/{cid}/test", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_test_missing_is_404(client, auth):
    assert client.post("/api/connections/nope/test", headers=auth).status_code == 404


def test_delete(client, auth, tmp_path):
    cid = _create(client, auth, tmp_path).json()["id"]
    assert client.delete(f"/api/connections/{cid}", headers=auth).status_code == 204
    assert client.get(f"/api/connections/{cid}", headers=auth).status_code == 404


def test_delete_default_is_422(client, auth):
    assert client.delete("/api/connections/default", headers=auth).status_code == 422


def test_delete_missing_is_404(client, auth):
    assert client.delete("/api/connections/nope", headers=auth).status_code == 404
