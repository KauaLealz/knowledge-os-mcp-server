def test_health(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_openapi_and_docs(client):
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200

