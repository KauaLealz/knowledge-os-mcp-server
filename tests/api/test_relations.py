"""Relações pela API: criar/apagar em lote (`RelationService`) e o grafo de um item no formato
do `item_graph` (`{nodes, edges, truncated, total_by_hop}`)."""

NODE_FIELDS = {"key", "id", "type", "subtype", "title", "summary", "scope", "status", "hop"}


def _three(mk):
    ws, dm, a = mk.tree()
    b = mk.item(ws["id"], dm["id"], "B", key="rule/b")
    c = mk.item(ws["id"], dm["id"], "C", key="rule/c")
    return ws, dm, a, b, c


def _rel(client, items):
    return client.post("/api/relations", json={"items": items})


def test_create_e_repetir_e_unchanged(client, mk):
    _, _, a, b, _ = _three(mk)
    r = _rel(client, [{"source": a["id"], "type": "related_to", "target": b["id"]}])
    assert r.status_code == 201, r.text
    assert [row["action"] for row in r.json()] == ["created"]
    r = _rel(client, [{"source": a["id"], "type": "related_to", "target": b["id"]}])
    assert [row["action"] for row in r.json()] == ["unchanged"]


def test_supersedes_arquiva_o_alvo(client, mk):
    _, _, a, b, _ = _three(mk)
    _rel(client, [{"source": a["id"], "type": "supersedes", "target": b["id"]}])
    assert client.get(f"/api/items/{b['id']}").json()["status"] == "archived"


def test_tipo_invalido_lista_os_validos_e_nada_grava(client, mk):
    _, _, a, b, c = _three(mk)
    r = _rel(client, [{"source": a["id"], "type": "related_to", "target": c["id"]},
                      {"source": a["id"], "type": "parent_of", "target": b["id"]}])
    assert r.status_code == 422
    assert "items[1]" in r.json()["detail"] and "depends_on" in r.json()["detail"]
    graph = client.get(f"/api/items/{a['id']}/graph").json()
    assert graph["edges"] == []


def test_auto_relacao_e_alvo_inexistente(client, mk):
    _, _, a, _, _ = _three(mk)
    r = _rel(client, [{"source": a["id"], "type": "related_to", "target": a["id"]}])
    assert r.status_code == 422
    r = _rel(client, [{"source": a["id"], "type": "related_to", "target": "nope"}])
    assert r.status_code == 404


def test_graph_no_formato_do_item_graph(client, mk):
    _, _, a, b, c = _three(mk)
    _rel(client, [{"source": a["id"], "type": "depends_on", "target": b["id"]},
                  {"source": c["id"], "type": "references", "target": a["id"]}])
    r = client.get(f"/api/items/{a['id']}/graph")
    assert r.status_code == 200, r.text
    g = r.json()
    assert set(g) == {"nodes", "edges", "truncated", "total_by_hop"}
    assert all(NODE_FIELDS <= set(n) for n in g["nodes"])
    hops = {n["title"]: n["hop"] for n in g["nodes"]}
    assert hops == {"Item": 0, "B": 1, "C": 1}
    a_ref = a["key"] or a["id"]
    assert {"from": a_ref, "type": "depends_on", "to": "rule/b"} in g["edges"]
    assert {"from": "rule/c", "type": "references", "to": a_ref} in g["edges"]
    assert g["truncated"] is False and g["total_by_hop"] == {"1": 2}
    out = client.get(f"/api/items/{a['id']}/graph", params={"direction": "out"}).json()
    assert {n["title"] for n in out["nodes"]} == {"Item", "B"}


def test_graph_limit_corta_e_marca_truncated(client, mk):
    _, _, a, b, c = _three(mk)
    _rel(client, [{"source": a["id"], "type": "related_to", "target": b["id"]},
                  {"source": a["id"], "type": "related_to", "target": c["id"]}])
    g = client.get(f"/api/items/{a['id']}/graph", params={"limit": 1}).json()
    assert g["truncated"] is True and g["total_by_hop"] == {"1": 2} and len(g["nodes"]) == 2


def test_graph_parametros_invalidos_e_item_inexistente(client, mk):
    _, _, a, _, _ = _three(mk)
    r = client.get(f"/api/items/{a['id']}/graph", params={"depth": 4})
    assert r.status_code == 422 and "depth" in r.json()["detail"]
    r = client.get(f"/api/items/{a['id']}/graph", params={"direction": "up"})
    assert r.status_code == 422 and "both" in r.json()["detail"]
    assert client.get("/api/items/nope/graph").status_code == 404


def test_delete_em_lote(client, mk):
    _, _, a, b, _ = _three(mk)
    item = {"source": a["id"], "type": "related_to", "target": b["id"]}
    _rel(client, [item])
    r = client.request("DELETE", "/api/relations", json={"items": [item]})
    assert r.status_code == 200 and [x["action"] for x in r.json()] == ["deleted"]
    r = client.request("DELETE", "/api/relations", json={"items": [item]})
    assert [x["action"] for x in r.json()] == ["missing"]
    assert client.get(f"/api/items/{a['id']}/graph").json()["edges"] == []


def test_rotas_antigas_de_relacao_sumiram(client, mk):
    _, _, a, _, _ = _three(mk)
    assert client.get(f"/api/items/{a['id']}/relations").status_code == 404
    assert client.get("/api/relations").status_code == 405


def test_graph_da_ficha_mostra_relacao_com_item_scoped_de_outro_project(client, mk):
    ws, dm, a = mk.tree()
    outro = mk.project(ws["id"], "Outro")
    b = mk.item(ws["id"], outro["id"], "B", key="rule/b", scope="scoped")
    r = _rel(client, [{"source": a["id"], "type": "related_to", "target": b["id"]}])
    assert r.status_code == 201, r.text
    g = client.get(f"/api/items/{a['id']}/graph").json()
    assert {n["title"] for n in g["nodes"]} == {"Item", "B"}
