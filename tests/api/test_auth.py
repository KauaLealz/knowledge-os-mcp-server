import pytest

from src.api import auth as auth_mod


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer token-errado"},
        {"Authorization": "Bearer test-token-x"},
    ],
)
def test_rejects_missing_or_wrong_token(client, headers):
    assert client.get("/api/workspaces", headers=headers).status_code == 401


def test_accepts_the_configured_token(client, auth):
    assert client.get("/api/workspaces", headers=auth).status_code == 200


def test_fail_closed_without_configured_token(client, auth):
    auth_mod.set_token(None)
    assert client.get("/api/workspaces", headers=auth).status_code == 401
    assert client.get("/api/workspaces", headers={"Authorization": "Bearer "}).status_code == 401


def test_set_token_replaces_the_previous_one(client, auth):
    auth_mod.set_token("novo-token")
    assert client.get("/api/workspaces", headers=auth).status_code == 401
    ok = client.get("/api/workspaces", headers={"Authorization": "Bearer novo-token"})
    assert ok.status_code == 200


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
