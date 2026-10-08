"""Roteamento de dados por X-Connection-Id e pela conexão padrão do connections.json."""

import pytest
from fastapi.testclient import TestClient

from knowledge_os.api.main import app
from knowledge_os.config import NO_CONNECTION_MESSAGE, ConfigManager


@pytest.fixture
def api():
    """Cliente sobre o home isolado do teste, começando sem nenhuma conexão."""
    yield TestClient(app)


def _conn(api, name, tmp_path):
    repo_path = tmp_path / f"repo-{name}"
    repo_path.mkdir()
    r = api.post("/api/connections", json={"name": name, "path": str(repo_path)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _hdr(cid):
    return {"X-Connection-Id": cid}


def _names(api, headers):
    r = api.get("/api/workspaces", headers=headers)
    assert r.status_code == 200, r.text
    return [w["name"] for w in r.json()]


def test_sem_conexao_as_rotas_de_dados_dizem_como_criar(api):
    r = api.get("/api/workspaces")
    assert r.status_code == 422 and r.json()["detail"] == NO_CONNECTION_MESSAGE
    assert api.get("/api/connections").json() == []


def test_header_isolates_connections(api, tmp_path):
    a, b = _conn(api, "A", tmp_path), _conn(api, "B", tmp_path)
    r = api.post("/api/workspaces", headers=_hdr(a), json={"name": "OnlyA"})
    assert r.status_code == 201
    assert _names(api, _hdr(a)) == ["OnlyA"]
    assert _names(api, _hdr(b)) == []
    assert _names(api, {}) == ["OnlyA"]  # sem header: a padrão (a primeira criada, A)
    # o mesmo nome em outra conexão é permitido
    assert api.post("/api/workspaces", headers=_hdr(b), json={"name": "OnlyA"}).status_code == 201


def test_data_routes_follow_header(api, tmp_path):
    a, b = _conn(api, "A", tmp_path), _conn(api, "B", tmp_path)
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
    assert renamed.status_code == 200 and renamed.json()["id"] == "w2"
    assert api.delete("/api/workspaces/w2", headers=_hdr(a)).status_code == 204


def test_without_header_uses_json_default(api, tmp_path):
    _conn(api, "A", tmp_path)
    b = _conn(api, "B", tmp_path)
    assert api.put(f"/api/connections/{b}/default").status_code == 200
    assert api.post("/api/workspaces", json={"name": "InB"}).status_code == 201
    assert _names(api, _hdr(b)) == ["InB"]
    assert _names(api, {}) == ["InB"]
    # a lista de conexões continua acessível e a conexão de dados não a afeta
    assert api.get("/api/connections").status_code == 200
    assert ConfigManager.load().default == b


def test_unknown_is_404_and_disabled_is_422(api, tmp_path):
    _conn(api, "Padrao", tmp_path)
    assert api.get("/api/workspaces", headers=_hdr("nope")).status_code == 404
    a = _conn(api, "A", tmp_path)
    assert api.patch(f"/api/connections/{a}", json={"enabled": False}).status_code == 200
    assert api.get("/api/workspaces", headers=_hdr(a)).status_code == 422
