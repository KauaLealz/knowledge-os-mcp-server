"""Projects e subjects pela API (v6: sem scope; listas por `rows()`)."""


def test_list_empty(client):
    assert client.get("/api/projects").json() == []


def test_create_get(client, mk):
    ws = mk.ws()
    r = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "D",
                                           "description": "x"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["workspace_id"] == ws["id"] and d["subjects"] == [] and d["items"] == 0
    assert "scope" not in d and "scope_explicit" not in d
    assert client.get(f"/api/projects/{d['id']}").json()["name"] == "D"


def test_create_workspace_missing_is_404(client):
    r = client.post("/api/projects", json={"workspace_id": "nope", "name": "D"})
    assert r.status_code == 404


def test_create_duplicate_is_422(client, mk):
    ws = mk.ws()
    mk.project(ws["id"], "D")
    r = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "D"})
    assert r.status_code == 422


def test_list_filter_by_workspace(client, mk):
    a, b = mk.ws("A"), mk.ws("B")
    mk.project(a["id"], "D1")
    mk.project(b["id"], "D2")
    r = client.get("/api/projects", params={"workspace_id": a["id"]})
    assert [d["name"] for d in r.json()] == ["D1"]
    assert len(client.get("/api/projects").json()) == 2


def test_get_missing_is_404(client):
    assert client.get("/api/projects/nope").status_code == 404


def test_update_nome(client, mk):
    ws = mk.ws()
    pj = mk.project(ws["id"], "D")
    r = client.put(f"/api/projects/{pj['id']}", json={"name": "D2", "description": "y"})
    assert r.status_code == 200 and (r.json()["name"], r.json()["description"]) == ("D2", "y")


def test_update_missing_is_404(client):
    assert client.put("/api/projects/nope", json={"name": "x"}).status_code == 404


def test_update_duplicate_is_422(client, mk):
    ws = mk.ws()
    mk.project(ws["id"], "A")
    b = mk.project(ws["id"], "B")
    assert client.put(f"/api/projects/{b['id']}", json={"name": "A"}).status_code == 422


def test_delete(client, mk):
    ws = mk.ws()
    pj = mk.project(ws["id"], "D")
    assert client.delete(f"/api/projects/{pj['id']}").status_code == 204
    assert client.get(f"/api/projects/{pj['id']}").status_code == 404


def test_delete_missing_is_404(client):
    assert client.delete("/api/projects/nope").status_code == 404


def test_mesmo_project_em_dois_workspaces_pede_workspace_id(client, mk):
    a, b = mk.ws("A"), mk.ws("B")
    mk.project(a["id"], "Geral")
    mk.project(b["id"], "Geral")
    assert client.get("/api/projects/geral").status_code == 422
    assert client.get("/api/projects/geral", params={"workspace_id": "b"}).json()[
        "workspace_id"] == "b"


# ---- subjects -------------------------------------------------------------------------------


def test_subject_create_list_update_delete(client, mk):
    ws = mk.ws()
    pj = mk.project(ws["id"], "P")
    sj = mk.subject(ws["id"], pj["id"], "Pix", description="pagamentos")
    assert (sj["name"], sj["description"], sj["items"]) == ("Pix", "pagamentos", 0)
    assert "scope" not in sj
    mk.item(ws["id"], pj["id"], "No pix", subject_id=sj["id"])
    r = client.get("/api/subjects", params={"workspace_id": ws["id"], "project_id": pj["id"]})
    assert r.status_code == 200 and [(s["name"], s["items"]) for s in r.json()] == [("Pix", 1)]
    q = {"workspace_id": ws["id"], "project_id": pj["id"]}
    r = client.put(f"/api/subjects/{sj['id']}", params=q, json={"name": "PIX novo"})
    assert r.status_code == 200 and r.json()["name"] == "PIX novo"
    assert client.get("/api/projects/p").json()["subjects"] == ["PIX novo"]
    assert client.delete("/api/subjects/pix-novo", params=q).status_code == 204
    assert client.get("/api/subjects", params=q).json() == []
    assert client.delete("/api/subjects/pix-novo", params=q).status_code == 404


def test_subject_duplicado_e_project_inexistente(client, mk):
    ws = mk.ws()
    pj = mk.project(ws["id"], "P")
    mk.subject(ws["id"], pj["id"], "S")
    r = client.post("/api/subjects",
                    json={"workspace_id": ws["id"], "project_id": pj["id"], "name": "S"})
    assert r.status_code == 422
    r = client.post("/api/subjects",
                    json={"workspace_id": ws["id"], "project_id": "nope", "name": "S"})
    assert r.status_code == 404
