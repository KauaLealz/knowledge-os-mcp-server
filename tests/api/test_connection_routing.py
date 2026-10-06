"""Roteamento de dados por X-Connection-Id e pelo default do connections.json."""

import pytest
from fastapi.testclient import TestClient

from knowledge_os.api.deps import get_artifacts_dir
from knowledge_os.api.main import app
from knowledge_os.config import ConfigManager
from tests.helpers_multidb import catalog  # noqa: F401


@pytest.fixture
def api(catalog, tmp_path):  # noqa: F811
    """Cliente sem override de engine: o roteamento real, sobre um catálogo temporário."""
    app.dependency_overrides[get_artifacts_dir] = lambda: tmp_path / "artifacts"
    yield TestClient(app)
    app.dependency_overrides.clear()


def _conn(api, name):
    r = api.post("/api/connections", json={
        "name": name, "db_type": "sqlite", "path": f"{name}.db"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _hdr(cid):
    return {"X-Connection-Id": cid}


def _names(api, headers):
    r = api.get("/api/workspaces", headers=headers)
    assert r.status_code == 200, r.text
    return [w["name"] for w in r.json()]


def test_header_isolates_connections(api):
    a, b = _conn(api, "A"), _conn(api, "B")
    r = api.post("/api/workspaces", headers=_hdr(a), json={"name": "OnlyA"})
    assert r.status_code == 201
    assert _names(api, _hdr(a)) == ["OnlyA"]
    assert _names(api, _hdr(b)) == []
    assert _names(api, {}) == []  # sem header: catálogo (default do JSON)
    # o mesmo nome em outra conexão é permitido
    assert api.post("/api/workspaces", headers=_hdr(b), json={"name": "OnlyA"}).status_code == 201


def test_data_routes_follow_header(api):
    a, b = _conn(api, "A"), _conn(api, "B")
    ws = api.post("/api/workspaces", headers=_hdr(a), json={"name": "W"}).json()
    dm = api.post("/api/projects", headers=_hdr(a),
                  json={"workspace_id": ws["id"], "name": "D"}).json()
    item = api.post("/api/items", headers=_hdr(a), json={
        "workspace_id": ws["id"], "project_id": dm["id"], "type": "knowledge",
        "memory_class": "longterm", "title": "T", "summary": "s", "content": "c"})
    assert item.status_code == 201, item.text
    assert api.get(f"/api/items/{item.json()['id']}", headers=_hdr(a)).status_code == 200
    assert api.get(f"/api/items/{item.json()['id']}", headers=_hdr(b)).status_code == 404
    assert api.get(f"/api/workspaces/{ws['id']}/tree", headers=_hdr(b)).status_code == 404
    renamed = api.put(f"/api/workspaces/{ws['id']}", headers=_hdr(a), json={"name": "W2"})
    assert renamed.status_code == 200
    assert api.delete(f"/api/workspaces/{ws['id']}", headers=_hdr(a)).status_code == 204


def test_without_header_uses_json_default(api):
    a = _conn(api, "A")
    assert api.put(f"/api/connections/{a}/default").status_code == 200
    assert api.post("/api/workspaces", json={"name": "InA"}).status_code == 201
    assert _names(api, _hdr(a)) == ["InA"]
    assert _names(api, _hdr("default")) == []
    assert _names(api, {}) == ["InA"]
    # a lista de conexões continua acessível e a conexão de dados não a afeta
    assert api.get("/api/connections").status_code == 200
    assert ConfigManager.load_or_create().default == a


def test_unknown_is_404_and_disabled_is_422(api):
    assert api.get("/api/workspaces", headers=_hdr("nope")).status_code == 404
    a = _conn(api, "A")
    assert api.patch(f"/api/connections/{a}", json={"enabled": False}).status_code == 200
    assert api.get("/api/workspaces", headers=_hdr(a)).status_code == 422
