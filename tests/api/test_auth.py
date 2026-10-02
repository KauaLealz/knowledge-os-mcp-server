import pytest


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}]
)
def test_rejects_missing_or_invalid_token(client, headers):
    assert client.get("/api/workspaces", headers=headers).status_code == 401


def test_accepts_bearer(client, auth):
    assert client.get("/api/workspaces", headers=auth).status_code == 200


def test_cors_headers(client):
    r = client.options(
        "/api/workspaces",
        headers={"Origin": "http://x.test", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] in ("*", "http://x.test")
