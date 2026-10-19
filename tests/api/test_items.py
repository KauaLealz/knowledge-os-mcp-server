"""Itens pela API no modelo v6: campos mínimos, links unificados, filtros por tipo/tag/subject,
atualização parcial, remoção. Sem subtype/scope/status/origin/ttl/feedback (tudo isso saiu)."""

V6_FIELDS = {"key", "id", "type", "title", "summary", "content", "tags", "links",
             "workspace", "project", "subject", "where", "created_at", "updated_at"}
REMOVED = {"subtype", "scope", "effective_scope", "scope_inherited_from", "status", "origin",
           "verified_at", "verified_commit", "ttl_days", "expires_at", "keywords", "source",
           "scope_paths", "labels", "memory_class", "importance", "confidence",
           "access_count", "last_accessed"}


def test_list_empty(client):
    assert client.get("/api/items").json() == {"items": [], "total": 0}


def test_create_returns_v6_item(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    r = client.post("/api/items", json={
        "workspace_id": ws["id"], "project_id": dm["id"], "key": "rule/money",
        "type": "rule", "title": "Money", "summary": "Use Money", "content": "Sempre Money.",
        "tags": ["pagamentos", "decision"],
        "links": [{"url": "https://x.test", "title": "Painel"}, {"path": "src/pay/**"}],
    })
    assert r.status_code == 201, r.text
    d = r.json()
    assert V6_FIELDS <= d.keys() and not (REMOVED & d.keys())
    assert (d["type"], d["key"], d["where"]) == ("rule", "rule/money", "WS/Dom")
    assert d["tags"] == ["decision", "pagamentos"]
    assert d["links"] == [{"url": "https://x.test", "title": "Painel"}, {"path": "src/pay/**"}]
    assert d["workspace_id"] == ws["id"] and d["project_id"] == dm["id"]
    got = client.get(f"/api/items/{d['id']}").json()
    assert got["links"] == d["links"] and got["tags"] == d["tags"]


def test_item_link_para_outro_item(client, mk):
    ws, dm, it = mk.tree()
    r = client.post("/api/items", json={
        "workspace_id": ws["id"], "project_id": dm["id"], "key": "howto/deploy",
        "type": "howto", "title": "Deploy", "summary": "como",
        "links": [{"item": it["key"] or it["id"], "rel": "depends_on"}]})
    assert r.status_code == 201, r.text
    assert r.json()["links"] == [{"item": it["key"] or it["id"], "rel": "depends_on"}]


def test_campos_antigos_e_removidos_dao_422(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    base = {"workspace_id": ws["id"], "project_id": dm["id"], "type": "rule",
            "title": "T", "summary": "S"}
    for field, value in (("subtype", "code"), ("scope", "global"), ("status", "active"),
                         ("origin", "user"), ("ttl_days", 30), ("keywords", "x"),
                         ("memory_class", "longterm"), ("labels", ["x"])):
        r = client.post("/api/items", json={**base, field: value})
        assert r.status_code == 422, (field, r.text)
        assert f"desconhecido(s): {field}" in r.json()["detail"] and "Válidos:" in r.json()["detail"]


def test_tipo_invalido_lista_os_validos(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    base = {"workspace_id": ws["id"], "project_id": dm["id"], "title": "T", "summary": "S"}
    r = client.post("/api/items", json={**base, "type": "spec"})  # spec virou work
    assert r.status_code == 422 and "work" in r.json()["detail"]
    r = client.post("/api/items", json={**base, "type": "knowledge"})
    assert r.status_code == 422 and "type inválido" in r.json()["detail"]


def test_tipo_work_substitui_spec(client, mk):
    ws, dm, _ = mk.tree()
    r = client.post("/api/items", json={"workspace_id": ws["id"], "project_id": dm["id"],
                                        "type": "work", "title": "Plano", "summary": "x",
                                        "tags": ["draft"]})
    assert r.status_code == 201 and r.json()["type"] == "work"


def test_get_missing_is_404(client):
    assert client.get("/api/items/nope").status_code == 404


def test_update_parcial_por_put_e_patch(client, mk):
    _, _, it = mk.tree()
    r = client.patch(f"/api/items/{it['id']}", json={
        "tags": ["security"], "links": [{"url": "https://a.test"}]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tags"] == ["security"] and d["links"] == [{"url": "https://a.test"}]
    assert d["title"] == it["title"]
    r = client.put(f"/api/items/{it['id']}", json={"confidence": 1})
    assert r.status_code == 422 and "confidence" in r.json()["detail"]


def test_list_filters_v6(client, mk):
    ws, dm, _ = mk.tree()
    dm2 = mk.project(ws["id"], "Dom2")
    mk.item(ws["id"], dm2["id"], "Howto", type="howto", tags=["deploy", "troubleshoot"])
    mk.item(ws["id"], dm2["id"], "Ctx", type="context", tags=["stack"])
    assert client.get("/api/items").json()["total"] == 3

    def titles(**params):
        r = client.get("/api/items", params=params)
        assert r.status_code == 200, r.text
        return sorted(i["title"] for i in r.json()["items"])

    assert titles(project_id=dm2["id"]) == ["Ctx", "Howto"]
    assert titles(project_id=f"{dm['id']},{dm2['id']}") == ["Ctx", "Howto", "Item"]
    assert titles(type="howto") == ["Howto"]
    assert titles(type="howto,context") == ["Ctx", "Howto"]
    assert titles(tag="deploy") == ["Howto"]
    assert titles(tag="stack") == ["Ctx"]
    assert titles(workspace_id="nope") == []
    r = client.get("/api/items", params={"type": "insight"})
    assert r.status_code == 422 and "Válidos" in r.json()["detail"]


def test_list_filtra_por_subject_id(client, mk):
    ws, dm, _ = mk.tree()
    sj = mk.subject(ws["id"], dm["id"], "Assunto")
    mk.item(ws["id"], dm["id"], "No assunto", subject_id=sj["id"])
    r = client.get("/api/items", params={"subject_id": sj["id"]})
    assert [i["title"] for i in r.json()["items"]] == ["No assunto"]


def test_list_limit_offset(client, mk):
    ws, dm, _ = mk.tree()
    mk.item(ws["id"], dm["id"], "B")
    mk.item(ws["id"], dm["id"], "C")
    assert len(client.get("/api/items", params={"limit": 2}).json()["items"]) == 2
    page = client.get("/api/items", params={"limit": 2, "offset": 2}).json()
    assert len(page["items"]) == 1 and page["total"] == 3


def test_delete(client, mk):
    _, _, it = mk.tree()
    assert client.delete(f"/api/items/{it['id']}").status_code == 204
    assert client.get(f"/api/items/{it['id']}").status_code == 404
    assert client.delete(f"/api/items/{it['id']}").status_code == 404


def test_rota_de_feedback_sumiu(client, mk):
    _, _, it = mk.tree()
    assert client.post(f"/api/items/{it['id']}/feedback",
                       json={"outcome": "helped"}).status_code in (404, 405)


def test_rotas_antigas_de_ajuste_sumiram(client, mk):
    _, _, it = mk.tree()
    for path in ("confidence", "importance", "memory_class", "labels"):
        assert client.put(f"/api/items/{it['id']}/{path}", json={"value": 1}).status_code in (
            404, 405)
        assert client.get(f"/api/items/{it['id']}/{path}").status_code in (404, 405)


def test_datas_saem_com_z_e_sem_campos_do_modelo_antigo(client, mk):
    _, _, it = mk.tree()
    for d in (it, client.get(f"/api/items/{it['id']}").json(),
              client.get("/api/items").json()["items"][0]):
        for name in ("created_at", "updated_at"):
            assert d[name].endswith("Z") and len(d[name]) == len("2026-10-08T20:31:15Z"), d[name]
        assert not (REMOVED & d.keys())


def test_id_inexistente_diz_qual_item_nao_foi_achado(client):
    r = client.get("/api/items/memory-class")
    assert r.status_code == 404 and r.json()["detail"] == "Item não encontrado: memory-class"
