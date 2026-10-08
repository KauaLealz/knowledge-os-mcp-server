"""O corpo da requisição nunca vence a rota: `id`/`key`/lugar do JSON não trocam o item
editado, não transformam uma criação em edição e não movem o item por fora dos campos de lugar
que a rota valida (`workspace_id`/`project_id`/`subject_id`)."""


def _two(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    return ws, dm, mk.item(ws["id"], dm["id"], "A"), mk.item(ws["id"], dm["id"], "B")


def test_put_com_outro_id_no_corpo_edita_o_item_da_rota(client, mk):
    _, _, a, b = _two(client, mk)
    r = client.put(f"/api/items/{a['id']}", json={"id": b["id"], "title": "Trocado"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == a["id"] and r.json()["title"] == "Trocado"
    assert client.get(f"/api/items/{b['id']}").json()["title"] == "B"


def test_patch_com_outro_id_no_corpo_edita_o_item_da_rota(client, mk):
    _, _, a, b = _two(client, mk)
    client.patch(f"/api/items/{a['id']}", json={"id": b["id"], "summary": "novo"})
    assert client.get(f"/api/items/{a['id']}").json()["summary"] == "novo"
    assert client.get(f"/api/items/{b['id']}").json()["summary"] != "novo"


def test_post_com_id_e_recusado_em_vez_de_mover(client, mk):
    ws, _, a, _ = _two(client, mk)
    other = mk.project(ws["id"], "Outro")
    r = client.post("/api/items", json={"workspace_id": ws["id"], "project_id": other["id"],
                                        "id": a["id"], "type": "rule", "title": "X",
                                        "summary": "s"})
    assert r.status_code == 422 and "não envie id" in r.text
    assert client.get(f"/api/items/{a['id']}").json()["project_id"] != other["id"]


def test_lugar_cru_no_corpo_nao_move_o_item(client, mk):
    ws, dm, a, _ = _two(client, mk)
    mk.project(ws["id"], "Outro")
    r = client.put(f"/api/items/{a['id']}", json={"workspace": "WS", "project": "Outro",
                                                  "title": "Fica"})
    assert r.status_code == 200, r.text
    assert r.json()["project_id"] == dm["id"] and r.json()["title"] == "Fica"


def test_post_com_lugar_cru_no_corpo_vale_o_do_campo_validado(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    r = client.post("/api/items", json={"workspace_id": ws["id"], "project_id": dm["id"],
                                        "workspace": "Outro", "project": "Novo",
                                        "type": "rule", "title": "X", "summary": "s"})
    assert r.status_code == 201, r.text
    assert (r.json()["workspace_id"], r.json()["project_id"]) == (ws["id"], dm["id"])
    assert [w["name"] for w in client.get("/api/workspaces").json()] == ["WS"]


def test_feedback_com_key_no_corpo_vale_para_o_item_da_rota(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    a = mk.item(ws["id"], dm["id"], "A", key="rule/a")
    b = mk.item(ws["id"], dm["id"], "B", key="rule/b")
    r = client.post(f"/api/items/{a['id']}/feedback",
                    json={"key": "rule/b", "outcome": "wrong", "note": "errado"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/items/{a['id']}").json()["status"] == "review"
    assert client.get(f"/api/items/{b['id']}").json()["status"] == "active"
