def test_dashboard_servido_em_ui(client):
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Knowledge OS" in resp.text


def test_health_continua_em_raiz(client):
    assert client.get("/").json()["status"] == "ok"


def test_api_nao_e_engolida_pelo_mount(client, auth):
    assert client.get("/api/workspaces", headers=auth).status_code == 200
