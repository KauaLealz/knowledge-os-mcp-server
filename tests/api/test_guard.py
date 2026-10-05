"""API local sem login: a proteção é Host/Origin (bind em 127.0.0.1, sem CORS)."""

import pytest


def test_api_responde_sem_authorization(client):
    assert client.get("/api/workspaces").status_code == 200


def test_origin_estranha_nao_recebe_cors(client):
    r = client.get("/", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in r.headers
    pre = client.options(
        "/api/workspaces",
        headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in pre.headers


def test_host_estranho_e_recusado_com_400(client):
    assert client.get("/", headers={"Host": "evil.test"}).status_code == 400
    assert client.get("/", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert client.get("/", headers={"Host": "localhost:8765"}).status_code == 200


@pytest.mark.parametrize("origin", ["http://evil.test", "null", "http://127.0.0.1:1"])
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_escrita_de_outra_origem_e_recusada(client, method, origin):
    r = getattr(client, method)("/api/workspaces/x", headers={"Origin": origin})
    assert r.status_code == 403
    assert r.json()["detail"] == "Origin não permitida"


def test_escrita_da_mesma_origem_e_aceita(client):
    r = client.post(
        "/api/workspaces", json={"name": "Local"}, headers={"Origin": "http://testserver"}
    )
    assert r.status_code == 201


def test_escrita_sem_origin_passa_curl_e_scripts(client):
    assert client.post("/api/workspaces", json={"name": "Script"}).status_code == 201


def test_leitura_de_outra_origem_nao_e_bloqueada_mas_nao_ganha_cors(client):
    r = client.get("/api/workspaces", headers={"Origin": "http://evil.test"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
