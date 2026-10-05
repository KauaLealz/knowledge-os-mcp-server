import json
import logging

import pytest

from src.config import ConfigManager
from src.services import connection_service

SECRET = "supersecret-123"


def _create(client, name="extra", **over):
    body = {"name": name, "db_type": "sqlite", "path": f"{name}.db"}
    body.update(over)
    return client.post("/api/connections", json=body)


def _pg(client, name="pg", **over):
    body = {"name": name, "db_type": "postgresql", "host": "127.0.0.1", "port": 1,
            "database": "kos", "username": "u", "password": SECRET}
    body.update(over)
    return client.post("/api/connections", json=body)


def test_list_has_catalog_marked_default(client):
    r = client.get("/api/connections")
    assert r.status_code == 200
    (c,) = r.json()
    assert c["id"] == "default" and c["is_catalog"] is True and c["is_default"] is True
    assert c["password_set"] is False and c["last_test"] is None


def test_create_get_list(client):
    r = _create(client)
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "extra" and c["path"] == "extra.db" and c["enabled"] is True
    assert c["password_set"] is False and c["is_default"] is False and c["is_catalog"] is False
    assert client.get(f"/api/connections/{c['id']}").json()["name"] == "extra"
    assert [x["id"] for x in client.get("/api/connections").json()] == [
        "default", c["id"]]


def test_create_duplicate_is_422(client):
    _create(client)
    assert _create(client).status_code == 422


@pytest.mark.parametrize("extra", [
    {"db_url": "postgresql://u:pw-embutida@h/db"},
    {"password_env": "KOS_PW"},
    {"qualquer": 1},
])
def test_create_forbids_legacy_and_unknown_fields(client, extra):
    r = _pg(client, **extra)
    assert r.status_code == 422
    assert "pw-embutida" not in r.text and SECRET not in r.text  # 422 não ecoa a entrada


@pytest.mark.parametrize("body", [
    {"name": "x", "db_type": "oracle", "path": "a.db"},
    {"name": "x", "db_type": "sqlite"},  # sem path
    {"name": "x", "db_type": "sqlite", "path": "a.db", "host": "h"},
    {"name": "x", "db_type": "postgresql", "host": "h"},  # sem database
    {"name": "x", "db_type": "postgresql", "host": "u:pw@h", "database": "d"},  # URL no host
    {"name": "x", "db_type": "mysql", "host": "h", "database": "d", "port": 70000},
    {"name": "default", "db_type": "sqlite", "path": "a.db"},
])
def test_create_invalid_is_422(client, body):
    assert client.post("/api/connections", json=body).status_code == 422


def test_get_missing_is_404(client):
    assert client.get("/api/connections/nope").status_code == 404


def test_password_is_write_only_and_stored_in_json(client):
    r = _pg(client)
    assert r.status_code == 201
    c = r.json()
    assert c["password_set"] is True and "password" not in c
    stored = json.loads(ConfigManager.CONNECTIONS_FILE.read_text(encoding="utf-8"))
    assert stored["connections"][0]["password"] == SECRET
    assert SECRET not in client.get(f"/api/connections/{c['id']}").text


def test_patch_password_semantics(client):
    cid = _pg(client).json()["id"]

    def stored():
        data = json.loads(ConfigManager.CONNECTIONS_FILE.read_text(encoding="utf-8"))
        return data["connections"][0]["password"]

    r = client.patch(f"/api/connections/{cid}", json={"host": "other"})
    assert r.status_code == 200 and r.json()["host"] == "other"
    assert r.json()["password_set"] is True and stored() == SECRET  # ausente mantém

    r = client.patch(f"/api/connections/{cid}", json={"password": "novo-valor"})
    assert r.json()["password_set"] is True and stored() == "novo-valor"
    assert "novo-valor" not in r.text

    r = client.patch(f"/api/connections/{cid}", json={"password": None})
    assert r.json()["password_set"] is False and stored() is None


def test_patch_blank_port_falls_back_to_default(client):
    cid = _pg(client).json()["id"]
    r = client.patch(f"/api/connections/{cid}", json={"port": None})
    assert r.status_code == 200 and r.json()["port"] == 5432


def test_patch_fields_and_validation(client):
    cid = _create(client).json()["id"]
    r = client.patch(f"/api/connections/{cid}",
                     json={"name": "renomeada", "path": "novo.db", "enabled": False})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["path"], r.json()["enabled"]) == (
        "renomeada", "novo.db", False)
    assert client.patch(f"/api/connections/{cid}",
                        json={"host": "h"}).status_code == 422  # host não é de SQLite
    assert client.patch(f"/api/connections/{cid}",
                        json={"db_url": "x"}).status_code == 422
    assert client.patch("/api/connections/nope",
                        json={"name": "a"}).status_code == 404


def test_catalog_cannot_be_edited_or_deleted(client):
    assert client.patch("/api/connections/default",
                        json={"name": "x"}).status_code == 422
    assert client.delete("/api/connections/default").status_code == 422


def test_test_endpoint_ok_and_last_test(client):
    cid = _create(client).json()["id"]
    r = client.post(f"/api/connections/{cid}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and isinstance(body["latency_ms"], int) and body["message"]
    last = client.get(f"/api/connections/{cid}").json()["last_test"]
    assert last["status"] == "ok" and last["latency_ms"] == body["latency_ms"]
    assert last["tested_at"]


def test_test_missing_is_404(client):
    assert client.post("/api/connections/nope/test").status_code == 404


def test_delete_204_then_404(client):
    cid = _create(client).json()["id"]
    assert client.delete(f"/api/connections/{cid}").status_code == 204
    assert client.get(f"/api/connections/{cid}").status_code == 404
    assert client.delete(f"/api/connections/{cid}").status_code == 404


def test_set_default_and_delete_default_blocked(client):
    cid = _create(client).json()["id"]
    r = client.put(f"/api/connections/{cid}/default")
    assert r.status_code == 200 and r.json()["is_default"] is True
    assert ConfigManager.load_or_create().default == cid
    rows = {c["id"]: c for c in client.get("/api/connections").json()}
    assert rows["default"]["is_default"] is False and rows[cid]["is_default"] is True
    assert client.delete(f"/api/connections/{cid}").status_code == 422
    # volta para o catálogo
    r = client.put("/api/connections/default/default")
    assert r.status_code == 200 and ConfigManager.load_or_create().default == "default"
    assert client.delete(f"/api/connections/{cid}").status_code == 204


def test_set_default_disabled_is_422_and_missing_is_404(client):
    cid = _create(client, enabled=False).json()["id"]
    assert client.put(f"/api/connections/{cid}/default").status_code == 422
    assert client.put("/api/connections/nope/default").status_code == 404


def test_schema_sync_dry_run_then_apply(client):
    cid = _create(client).json()["id"]
    dry = client.post(f"/api/connections/{cid}/schema-sync?dry_run=true")
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True and "workspaces" in dry.json()["tables_created"]
    again = client.post(f"/api/connections/{cid}/schema-sync?dry_run=true").json()
    assert "workspaces" in again["tables_created"]  # dry-run não gravou nada
    done = client.post(f"/api/connections/{cid}/schema-sync?dry_run=false").json()
    assert done["dry_run"] is False and done["status"] == "created"
    final = client.post(f"/api/connections/{cid}/schema-sync?dry_run=true").json()
    assert final["status"] == "up_to_date" and final["tables_created"] == []


def test_schema_sync_missing_is_404(client):
    assert client.post("/api/connections/nope/schema-sync").status_code == 404


def test_secret_never_appears_anywhere(client, caplog, capsys, monkeypatch):
    """A senha não aparece em nenhuma resposta, nem em log/stderr, nem em erro de driver."""
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []

    def call(method, url, **kw):
        r = client.request(method, url, **kw)
        seen.append(r.text)
        return r

    created = call("POST", "/api/connections", json={
        "name": "pg", "db_type": "postgresql", "host": "127.0.0.1", "port": 1,
        "database": "kos", "username": "u", "password": SECRET})
    cid = created.json()["id"]
    call("GET", "/api/connections")
    call("GET", f"/api/connections/{cid}")
    call("PATCH", f"/api/connections/{cid}", json={"password": SECRET, "host": "localhost"})
    call("PATCH", f"/api/connections/{cid}", json={"db_url": f"postgresql://u:{SECRET}@h/d"})
    call("POST", "/api/connections", json={"name": "z", "db_type": "sqlite", "path": "z.db",
                                          "password": SECRET})  # 422: SQLite sem senha
    call("POST", "/api/connections", json={"name": "y", "db_type": "mysql", "host": f"u:{SECRET}@h",
                                          "database": "d"})
    call("POST", f"/api/connections/{cid}/test")  # falha de conexão real
    # um driver que ecoa a senha na mensagem de erro
    def boom(engine):
        raise RuntimeError(f"password authentication failed ({SECRET})")
    monkeypatch.setattr(connection_service, "_probe", boom)
    failed = call("POST", f"/api/connections/{cid}/test")
    assert failed.json()["status"] == "error" and "***" in failed.json()["message"]
    call("POST", f"/api/connections/{cid}/schema-sync?dry_run=true")
    call("POST", f"/api/connections/{cid}/schema-sync?dry_run=false")
    call("PUT", f"/api/connections/{cid}/default")

    out, err = capsys.readouterr()
    assert all(SECRET not in text for text in [*seen, caplog.text, out, err])
    assert len(seen) >= 11
