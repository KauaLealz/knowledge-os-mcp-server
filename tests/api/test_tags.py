"""Tags gerenciadas pela API: lista com contagem, criar, renomear (mescla se já existe) e
apagar com prévia (`confirm`)."""


def _tags(client):
    r = client.get("/api/tags")
    assert r.status_code == 200, r.text
    return {t["name"]: t["count"] for t in r.json()}


def test_lista_com_contagem_inclui_vocabulario_sem_item(client, mk):
    ws, dm, _ = mk.tree()
    mk.item(ws["id"], dm["id"], "A", tags=["pix", "pagamentos"])
    mk.item(ws["id"], dm["id"], "B", tags=["pix"])
    r = client.post("/api/tags", json={"names": ["vazia", "pix"]})
    assert r.status_code == 201, r.text
    assert r.json()["created"] == ["vazia"] and r.json()["existing"] == ["pix"]
    assert _tags(client) == {"pagamentos": 1, "pix": 2, "vazia": 0}
    assert client.get("/api/tags").json()[0] == {"name": "pagamentos", "count": 1}


def test_create_normaliza_e_recusa_invalida(client):
    r = client.post("/api/tags", json={"names": ["Pagamentos PIX"]})
    assert r.status_code == 201 and r.json()["created"] == ["pagamentos-pix"]
    r = client.post("/api/tags", json={"names": ["!!!"]})
    assert r.status_code == 422 and "kebab-case" in r.json()["detail"]
    assert client.post("/api/tags", json={"names": []}).status_code == 422


def test_renomear_e_mesclar(client, mk):
    ws, dm, _ = mk.tree()
    a = mk.item(ws["id"], dm["id"], "A", tags=["pix"])
    b = mk.item(ws["id"], dm["id"], "B", tags=["pagamento", "pix"])
    r = client.put("/api/tags/pagamento", json={"new_name": "pagamentos"})
    assert r.status_code == 200 and r.json() == {"renamed": 1, "merged": False}
    r = client.put("/api/tags/pix", json={"new_name": "pagamentos"})
    assert r.status_code == 200 and r.json() == {"renamed": 2, "merged": True}
    assert _tags(client) == {"pagamentos": 2}
    assert client.get(f"/api/items/{a['id']}").json()["tags"] == ["pagamentos"]
    assert client.get(f"/api/items/{b['id']}").json()["tags"] == ["pagamentos"]
    assert client.put("/api/tags/nope", json={"new_name": "x"}).status_code == 404


def test_apagar_com_previa_e_confirmacao(client, mk):
    ws, dm, _ = mk.tree()
    it = mk.item(ws["id"], dm["id"], "A", tags=["pix", "deploy"])
    r = client.delete("/api/tags/pix")
    assert r.status_code == 200
    assert r.json() == {"status": "preview", "tags": [{"name": "pix", "items": 1}]}
    assert "pix" in _tags(client)
    r = client.delete("/api/tags/pix", params={"confirm": True})
    assert r.status_code == 200 and r.json()["status"] == "deleted"
    assert "pix" not in _tags(client)
    assert client.get(f"/api/items/{it['id']}").json()["tags"] == ["deploy"]
    assert client.delete("/api/tags/nope").status_code == 404


def test_rotas_antigas_de_tag_no_item_sumiram(client, mk):
    _, _, it = mk.tree()
    assert client.get(f"/api/items/{it['id']}/tags").status_code == 404
    assert client.post(f"/api/items/{it['id']}/tags", json={"tag_id": "x"}).status_code == 404
