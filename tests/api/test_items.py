def test_list_empty(client):
    assert client.get("/api/items").json() == {"items": [], "total": 0}


def test_create_returns_full_item(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    r = client.post("/api/items", json={
        "workspace_id": ws["id"], "project_id": dm["id"], "type": "knowledge",
        "memory_class": "longterm", "title": "T", "summary": "S", "content": "C",
        "confidence": 90, "importance": 8, "tags": ["spring"], "labels": ["official"],
    })
    assert r.status_code == 201
    d = r.json()
    assert d["tags"] == ["spring"] and d["labels"] == ["official"]
    assert d["confidence"] == 90 and d["access_count"] == 0


def test_create_invalid_type_is_422(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    r = client.post("/api/items", json={
        "workspace_id": ws["id"], "project_id": dm["id"], "type": "bogus",
        "memory_class": "longterm", "title": "T", "summary": "S", "content": "C"})
    assert r.status_code == 422


def test_create_ephemeral_without_ttl_is_422(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    r = client.post("/api/items", json={
        "workspace_id": ws["id"], "project_id": dm["id"], "type": "context",
        "memory_class": "ephemeral", "title": "T", "summary": "S", "content": "C"})
    assert r.status_code == 422


def test_create_unknown_workspace_is_404(client):
    r = client.post("/api/items", json={
        "workspace_id": "x", "project_id": "y", "type": "context", "memory_class": "working",
        "title": "T", "summary": "S", "content": "C"})
    assert r.status_code == 404


def test_get(client, mk):
    _, _, it = mk.tree()
    r = client.get(f"/api/items/{it['id']}")
    assert r.status_code == 200
    assert r.json()["title"] == "Item"


def test_get_missing_is_404(client):
    assert client.get("/api/items/nope").status_code == 404


def test_list_filters(client, mk):
    ws, dm, _ = mk.tree()
    dm2 = mk.project(ws["id"], "Dom2")
    mk.item(ws["id"], dm2["id"], "Other", type="rule")
    assert len(client.get("/api/items").json()["items"]) == 2
    r = client.get("/api/items", params={"project_id": dm2["id"]})
    assert [i["title"] for i in r.json()["items"]] == ["Other"]
    r = client.get("/api/items", params={"workspace_id": ws["id"], "type": "rule"})
    assert len(r.json()["items"]) == 1
    r = client.get("/api/items", params={"workspace_id": "nope"})
    assert r.json() == {"items": [], "total": 0}


def test_list_limit_offset(client, mk):
    ws, dm, _ = mk.tree()
    mk.item(ws["id"], dm["id"], "B")
    mk.item(ws["id"], dm["id"], "C")
    assert len(client.get("/api/items", params={"limit": 2}).json()["items"]) == 2
    assert len(client.get("/api/items", params={"limit": 2, "offset": 2}).json()["items"]) == 1


def test_list_filtra_por_subject_id(client, mk, engine):
    from sqlalchemy.orm import Session

    from knowledge_os.services.subject_service import SubjectService

    ws, dm, _ = mk.tree()
    with Session(engine) as s:
        subj = SubjectService(s).create(dm["id"], "Assunto")
        subj_id = subj.id
    mk.item(ws["id"], dm["id"], "Com assunto", subject_id=subj_id)
    r = client.get("/api/items", params={"subject_id": subj_id})
    assert [i["title"] for i in r.json()["items"]] == ["Com assunto"]


def test_list_filtra_por_varios_project_id_e_subject_id_separados_por_virgula(client, mk, engine):
    from sqlalchemy.orm import Session

    from knowledge_os.services.subject_service import SubjectService

    ws = mk.ws()
    p1 = mk.project(ws["id"], "P1")
    p2 = mk.project(ws["id"], "P2")
    p3 = mk.project(ws["id"], "P3")
    with Session(engine) as s:
        subj = SubjectService(s).create(p1["id"], "Assunto")
        subj_id = subj.id
    mk.item(ws["id"], p1["id"], "A", subject_id=subj_id)
    mk.item(ws["id"], p2["id"], "B")
    mk.item(ws["id"], p3["id"], "C")

    r = client.get("/api/items", params={"project_id": f"{p1['id']},{p2['id']}"})
    assert {i["title"] for i in r.json()["items"]} == {"A", "B"}

    r = client.get("/api/items", params={"subject_id": subj_id})
    assert [i["title"] for i in r.json()["items"]] == ["A"]


def test_list_total_independe_do_limit(client, mk):
    """`total` é o total real sem o corte de limit/offset — é o que a paginação usa."""
    ws, dm, _ = mk.tree()
    mk.item(ws["id"], dm["id"], "B")
    mk.item(ws["id"], dm["id"], "C")
    r = client.get("/api/items", params={"limit": 1})
    assert r.json()["total"] == 3
    assert len(r.json()["items"]) == 1


def test_update(client, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}", json={"summary": "Novo", "importance": 3})
    assert r.status_code == 200
    assert r.json()["summary"] == "Novo" and r.json()["importance"] == 3
    assert r.json()["content"] == "Conteudo Item"


def test_update_invalid_is_422(client, mk):
    _, _, it = mk.tree()
    assert client.put(f"/api/items/{it['id']}", json={"confidence": 500}).status_code == 422


def test_update_missing_is_404(client):
    assert client.put("/api/items/nope", json={"summary": "x"}).status_code == 404


def test_delete(client, mk):
    _, _, it = mk.tree()
    assert client.delete(f"/api/items/{it['id']}").status_code == 204
    assert client.get(f"/api/items/{it['id']}").status_code == 404


def test_delete_missing_is_404(client):
    assert client.delete("/api/items/nope").status_code == 404


def test_set_confidence(client, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/confidence", json={"value": 42})
    assert r.status_code == 200 and r.json()["confidence"] == 42


def test_set_confidence_out_of_range_is_422(client, mk):
    _, _, it = mk.tree()
    assert client.put(f"/api/items/{it['id']}/confidence", json={"value": 101}).status_code == 422


def test_set_importance(client, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/importance", json={"value": 9})
    assert r.status_code == 200 and r.json()["importance"] == 9
    assert client.put(f"/api/items/{it['id']}/importance", json={"value": 11}).status_code == 422


def test_set_memory_class_promotes(client, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/memory_class", json={"memory_class": "canonical"})
    assert r.status_code == 200 and r.json()["memory_class"] == "canonical"


def test_set_memory_class_downgrade_is_422(client, mk):
    _, _, it = mk.tree()
    r = client.put(f"/api/items/{it['id']}/memory_class", json={"memory_class": "working"})
    assert r.status_code == 422


def test_set_memory_class_missing_item_is_404(client):
    r = client.put("/api/items/nope/memory_class", json={"memory_class": "canonical"})
    assert r.status_code == 404
