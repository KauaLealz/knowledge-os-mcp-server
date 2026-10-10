"""Projects e subjects pela API (v2): `scope` em create/update, listas por `rows()` com o
herdado indicado (`scope_inherited_from`)."""


def test_list_empty(client):
    assert client.get("/api/projects").json() == []


def test_create_get_com_scope(client, mk):
    ws = mk.ws()
    r = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "D",
                                           "description": "x", "scope": "workspace"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["workspace_id"] == ws["id"] and d["subjects"] == [] and d["items"] == 0
    assert (d["scope"], d["scope_explicit"], d["scope_inherited_from"]) == (
        "workspace", "workspace", None)
    assert client.get(f"/api/projects/{d['id']}").json()["name"] == "D"


def test_scope_herdado_do_workspace_e_indicado(client, mk):
    ws = mk.ws(scope="global")
    pj = mk.project(ws["id"], "P")
    assert (pj["scope"], pj["scope_explicit"], pj["scope_inherited_from"]) == (
        "global", None, "workspace")
    plain = mk.project(mk.ws("Plain")["id"], "Q")
    assert (plain["scope"], plain["scope_inherited_from"]) == ("scoped", None)


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


def test_update_nome_e_scope(client, mk):
    ws = mk.ws()
    pj = mk.project(ws["id"], "D")
    r = client.put(f"/api/projects/{pj['id']}", json={"name": "D2", "description": "y"})
    assert r.status_code == 200 and (r.json()["name"], r.json()["description"]) == ("D2", "y")
    r = client.put("/api/projects/d2", json={"scope": "global"},
                   params={"workspace_id": ws["id"]})
    assert r.status_code == 200 and r.json()["scope"] == "global"
    r = client.put("/api/projects/d2", json={"scope": ""})
    assert r.json()["scope_explicit"] is None
    r = client.put("/api/projects/d2", json={"scope": "x"})
    assert r.status_code == 422 and "Válidos" in r.json()["detail"]


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
    ws = mk.ws(scope="workspace")
    pj = mk.project(ws["id"], "P")
    sj = mk.subject(ws["id"], pj["id"], "Pix", description="pagamentos")
    assert (sj["name"], sj["description"], sj["items"]) == ("Pix", "pagamentos", 0)
    assert (sj["scope"], sj["scope_explicit"], sj["scope_inherited_from"]) == (
        "workspace", None, "workspace")
    mk.item(ws["id"], pj["id"], "No pix", subject_id=sj["id"])
    r = client.get("/api/subjects", params={"workspace_id": ws["id"], "project_id": pj["id"]})
    assert r.status_code == 200 and [(s["name"], s["items"]) for s in r.json()] == [("Pix", 1)]
    q = {"workspace_id": ws["id"], "project_id": pj["id"]}
    r = client.put(f"/api/subjects/{sj['id']}", params=q, json={"scope": "global"})
    assert r.status_code == 200, r.text
    assert (r.json()["scope"], r.json()["scope_inherited_from"]) == ("global", None)
    r = client.put(f"/api/subjects/{sj['id']}", params=q, json={"name": "PIX novo"})
    assert r.json()["name"] == "PIX novo" and r.json()["scope"] == "global"
    assert client.get("/api/projects/p").json()["subjects"] == ["PIX novo"]
    assert client.delete("/api/subjects/pix-novo", params=q).status_code == 204
    assert client.get("/api/subjects", params=q).json() == []
    assert client.delete("/api/subjects/pix-novo", params=q).status_code == 404


def test_subject_herda_do_project(client, mk):
    ws = mk.ws()
    pj = mk.project(ws["id"], "P", scope="global")
    sj = mk.subject(ws["id"], pj["id"], "S")
    assert (sj["scope"], sj["scope_inherited_from"]) == ("global", "project")


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
