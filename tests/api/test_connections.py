import json
import subprocess

import pytest

from knowledge_os.config import ConfigManager


def _bare_repo(tmp_path, name="remote.git"):
    """Repositório git bare local: um remote de verdade, clonável sem rede."""
    path = tmp_path / name
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)
    return str(path)


_counter = iter(range(10_000))


def _create(client, tmp_path, name="extra", **over):
    path = tmp_path / f"repo-{next(_counter)}"
    path.mkdir()
    body = {"name": name, "path": str(path)}
    body.update(over)
    return client.post("/api/connections", json=body)


def test_list_has_catalog_marked_default(client, tmp_path):
    r = client.get("/api/connections")
    assert r.status_code == 200
    (c,) = r.json()
    assert c["id"] == "default" and c["is_catalog"] is True and c["is_default"] is True
    assert c["remote_url"] is None and c["last_test"] is None


def test_create_get_list(client, tmp_path):
    r = _create(client, tmp_path)
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "extra" and c["enabled"] is True
    assert c["remote_url"] is None and c["is_default"] is False and c["is_catalog"] is False
    assert client.get(f"/api/connections/{c['id']}").json()["name"] == "extra"
    assert [x["id"] for x in client.get("/api/connections").json()] == [
        "default", c["id"]]


def test_create_duplicate_is_422(client, tmp_path):
    _create(client, tmp_path)
    assert _create(client, tmp_path).status_code == 422


def test_create_com_remote_url_e_review_mode(client, tmp_path):
    remote = _bare_repo(tmp_path)
    r = _create(client, tmp_path, name="gh", remote_url=remote, review_mode="pr")
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["remote_url"] == remote and c["review_mode"] == "pr"


@pytest.mark.parametrize("extra", [
    {"db_type": "sqlite"},
    {"db_url": "postgresql://u:pw@h/db"},
    {"qualquer": 1},
])
def test_create_forbids_legacy_and_unknown_fields(client, extra, tmp_path):
    r = _create(client, tmp_path, **extra)
    assert r.status_code == 422


@pytest.mark.parametrize("body", [
    {"name": "x", "review_mode": "oracle"},
    {"name": "default"},  # nome reservado
])
def test_create_invalid_is_422(client, body, tmp_path):
    assert client.post("/api/connections", json=body).status_code == 422


def test_create_com_remote_inalcancavel_e_422(client, tmp_path):
    r = _create(client, tmp_path, name="down", remote_url="https://127.0.0.1:1/nope.git")
    assert r.status_code == 422


def test_get_missing_is_404(client, tmp_path):
    assert client.get("/api/connections/nope").status_code == 404


def test_remote_url_fica_no_json(client, tmp_path):
    remote = _bare_repo(tmp_path)
    r = _create(client, tmp_path, name="gh", remote_url=remote)
    assert r.status_code == 201
    c = r.json()
    stored = json.loads(ConfigManager.CONNECTIONS_FILE.read_text(encoding="utf-8"))
    assert stored["connections"][0]["remote_url"] == remote
    assert client.get(f"/api/connections/{c['id']}").json()["remote_url"] == remote


def test_patch_name_and_enabled(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.patch(f"/api/connections/{cid}", json={"name": "renomeada", "enabled": False})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["enabled"]) == ("renomeada", False)


def test_patch_remote_url_and_review_mode(client, tmp_path):
    remote = _bare_repo(tmp_path)
    cid = _create(client, tmp_path).json()["id"]
    r = client.patch(f"/api/connections/{cid}", json={"remote_url": remote, "review_mode": "pr"})
    assert r.status_code == 200
    assert r.json()["remote_url"] == remote and r.json()["review_mode"] == "pr"
    r = client.patch(f"/api/connections/{cid}", json={"remote_url": None})
    assert r.status_code == 200 and r.json()["remote_url"] is None


def test_patch_fields_and_validation(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.patch(f"/api/connections/{cid}", json={"name": "renomeada"})
    assert r.status_code == 200 and r.json()["name"] == "renomeada"
    assert client.patch(f"/api/connections/{cid}",
                        json={"review_mode": "sync"}).status_code == 422
    assert client.patch("/api/connections/nope",
                        json={"name": "a"}).status_code == 404


def test_catalog_cannot_be_edited_or_deleted(client, tmp_path):
    assert client.patch("/api/connections/default",
                        json={"name": "x"}).status_code == 422
    assert client.delete("/api/connections/default").status_code == 422


def test_test_endpoint_ok_and_last_test(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.post(f"/api/connections/{cid}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and isinstance(body["latency_ms"], int) and body["message"]
    last = client.get(f"/api/connections/{cid}").json()["last_test"]
    assert last["status"] == "ok" and last["latency_ms"] == body["latency_ms"]
    assert last["tested_at"]


def test_test_missing_is_404(client, tmp_path):
    assert client.post("/api/connections/nope/test").status_code == 404


def test_delete_204_then_404(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    assert client.delete(f"/api/connections/{cid}").status_code == 204
    assert client.get(f"/api/connections/{cid}").status_code == 404
    assert client.delete(f"/api/connections/{cid}").status_code == 404


def test_set_default_e_delete_da_default_passa_o_posto(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.put(f"/api/connections/{cid}/default")
    assert r.status_code == 200 and r.json()["is_default"] is True
    assert ConfigManager.load_or_create().default == cid
    rows = {c["id"]: c for c in client.get("/api/connections").json()}
    assert rows["default"]["is_default"] is False and rows[cid]["is_default"] is True
    # apagar a default é permitido: sem outra habilitada, o posto volta para o catálogo
    assert client.delete(f"/api/connections/{cid}").status_code == 204
    assert ConfigManager.load_or_create().default == "default"


def test_set_default_disabled_is_422_and_missing_is_404(client, tmp_path):
    cid = _create(client, tmp_path, enabled=False).json()["id"]
    assert client.put(f"/api/connections/{cid}/default").status_code == 422
    assert client.put("/api/connections/nope/default").status_code == 404


def test_schema_sync_dry_run_then_apply(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    dry = client.post(f"/api/connections/{cid}/schema-sync?dry_run=true")
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True
    done = client.post(f"/api/connections/{cid}/schema-sync?dry_run=false").json()
    assert done["dry_run"] is False and done["status"] in ("created", "up_to_date")
    final = client.post(f"/api/connections/{cid}/schema-sync?dry_run=true").json()
    assert final["status"] == "up_to_date" and final["tables_created"] == []


def test_schema_sync_missing_is_404(client, tmp_path):
    assert client.post("/api/connections/nope/schema-sync").status_code == 404
