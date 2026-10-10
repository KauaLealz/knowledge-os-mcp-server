"""Itens pela API no modelo v2: campos novos, filtros, atualização parcial, feedback e
remoção. Erros de validação trazem a mensagem do serviço (que diz como corrigir)."""

V2_FIELDS = {"subtype", "scope", "effective_scope", "scope_inherited_from", "links", "origin",
             "verified_at", "verified_commit", "where"}
REMOVED = {"labels", "memory_class", "importance", "confidence"}


def test_list_empty(client):
    assert client.get("/api/items").json() == {"items": [], "total": 0}


def test_create_returns_v2_item(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    r = client.post("/api/items", json={
        "workspace_id": ws["id"], "project_id": dm["id"], "key": "rule/money",
        "type": "rule", "subtype": "code", "scope": "workspace", "title": "Money",
        "summary": "Use Money", "content": "Sempre Money.", "tags": ["pagamentos"],
        "links": [{"title": "Painel", "url": "https://x.test"}], "origin": "user",
        "ttl_days": 30,
    })
    assert r.status_code == 201, r.text
    d = r.json()
    assert V2_FIELDS <= d.keys() and not (REMOVED & d.keys())
    assert (d["type"], d["subtype"], d["scope"], d["effective_scope"]) == (
        "rule", "code", "workspace", "workspace")
    assert d["scope_inherited_from"] is None
    assert d["links"] == [{"title": "Painel", "url": "https://x.test"}]
    assert d["origin"] == "user" and d["where"] == "WS/Dom" and d["key"] == "rule/money"
    assert d["tags"] == ["pagamentos"] and d["ttl_days"] == 30 and d["expires_at"]
    assert d["verified_at"] is None and d["verified_commit"] is None
    assert d["workspace_id"] == ws["id"] and d["project_id"] == dm["id"]
    got = client.get(f"/api/items/{d['id']}").json()
    assert got["subtype"] == "code" and got["links"] == d["links"]


def test_origin_padrao_e_agent_e_scope_herdado_e_indicado(client, mk):
    ws = mk.ws(scope="global")
    dm = mk.project(ws["id"])
    it = mk.item(ws["id"], dm["id"])
    assert it["origin"] == "agent"
    assert it["scope"] is None and it["effective_scope"] == "global"
    assert it["scope_inherited_from"] == "workspace"
    sj = mk.subject(ws["id"], dm["id"], "Pix", scope="scoped")
    it2 = mk.item(ws["id"], dm["id"], "No assunto", subject_id=sj["id"])
    assert (it2["effective_scope"], it2["scope_inherited_from"]) == ("scoped", "subject")
    plain = mk.item(mk.ws("Outro")["id"], mk.project("outro", "P")["id"])
    assert (plain["effective_scope"], plain["scope_inherited_from"]) == ("scoped", None)


def test_campo_antigo_e_422_com_a_mensagem_do_servico(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    for field, value in (("memory_class", "longterm"), ("confidence", 90), ("importance", 5),
                         ("labels", ["x"])):
        r = client.post("/api/items", json={
            "workspace_id": ws["id"], "project_id": dm["id"], "type": "rule",
            "title": "T", "summary": "S", field: value})
        assert r.status_code == 422, field
        detail = r.json()["detail"]
        assert isinstance(detail, str) and f"desconhecido(s): {field}" in detail
        assert "Válidos:" in detail


def test_tipo_e_subtipo_invalidos_listam_os_validos(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    base = {"workspace_id": ws["id"], "project_id": dm["id"], "title": "T", "summary": "S"}
    r = client.post("/api/items", json={**base, "type": "knowledge"})
    assert r.status_code == 422
    assert "type inválido" in r.json()["detail"] and "howto" in r.json()["detail"]
    r = client.post("/api/items", json={**base, "type": "howto", "subtype": "decision"})
    assert r.status_code == 422
    assert "procedure, troubleshoot" in r.json()["detail"]
    r = client.post("/api/items", json={**base, "type": "rule", "status": "done"})
    assert r.status_code == 422 and "só em spec" in r.json()["detail"]


def test_create_unknown_workspace_is_422_or_404(client):
    r = client.post("/api/items", json={
        "workspace_id": "x", "project_id": "y", "type": "context", "title": "T", "summary": "S"})
    assert r.status_code in (404, 422)


def test_get_missing_is_404(client):
    assert client.get("/api/items/nope").status_code == 404


def test_update_parcial_por_put_e_patch(client, mk):
    _, _, it = mk.tree()
    r = client.patch(f"/api/items/{it['id']}", json={
        "subtype": "decision", "scope": "global", "links": [{"url": "https://a.test"}]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["subtype"], d["scope"], d["effective_scope"]) == ("decision", "global", "global")
    assert d["links"] == [{"title": "https://a.test", "url": "https://a.test"}]
    assert d["title"] == it["title"]
    r = client.put(f"/api/items/{it['id']}", json={"scope": None, "status": "review"})
    assert r.status_code == 200
    assert r.json()["scope"] is None and r.json()["effective_scope"] == "scoped"
    assert r.json()["status"] == "review"
    r = client.put(f"/api/items/{it['id']}", json={"confidence": 1})
    assert r.status_code == 422 and "confidence" in r.json()["detail"]


def test_origin_invalido_lista_os_validos(client, mk):
    _, _, it = mk.tree()
    r = client.patch(f"/api/items/{it['id']}", json={"origin": "bogus"})
    assert r.status_code == 422 and "origin inválido" in r.json()["detail"]


def test_list_filters_v2(client, mk):
    ws, dm, _ = mk.tree()
    dm2 = mk.project(ws["id"], "Dom2", scope="workspace")
    mk.item(ws["id"], dm2["id"], "Howto", type="howto", subtype="troubleshoot",
            tags=["deploy"], origin="user", status="review")
    mk.item(ws["id"], dm2["id"], "Ctx", type="context", subtype="stack", scope="global")
    assert client.get("/api/items").json()["total"] == 3

    def titles(**params):
        r = client.get("/api/items", params=params)
        assert r.status_code == 200, r.text
        return sorted(i["title"] for i in r.json()["items"])

    assert titles(project_id=dm2["id"]) == ["Ctx", "Howto"]
    assert titles(project_id=f"{dm['id']},{dm2['id']}") == ["Ctx", "Howto", "Item"]
    assert titles(type="howto") == ["Howto"]
    assert titles(type="howto,context") == ["Ctx", "Howto"]
    assert titles(subtype="stack") == ["Ctx"]
    assert titles(status="review") == ["Howto"]
    assert titles(origin="user") == ["Howto"]
    assert titles(tag="deploy") == ["Howto"]
    assert titles(scope="global") == ["Ctx"]
    assert titles(scope="workspace") == ["Howto"]  # herdado do project
    assert titles(scope="scoped") == ["Item"]
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


def test_feedback_wrong_poe_em_review_e_verified_grava_a_data(client, mk):
    _, _, it = mk.tree()
    r = client.post(f"/api/items/{it['id']}/feedback",
                    json={"outcome": "wrong", "note": "regra mudou"})
    assert r.status_code == 200, r.text
    assert r.json() == {"applied": 1, "missing": []}
    got = client.get(f"/api/items/{it['id']}").json()
    assert got["status"] == "review" and "regra mudou" in got["content"]
    r = client.post(f"/api/items/{it['id']}/feedback", json={"outcome": "verified"})
    assert r.status_code == 200
    got = client.get(f"/api/items/{it['id']}").json()
    assert got["verified_at"] and got["status"] == "review"  # verified não reativa


def test_feedback_invalido_e_item_inexistente(client, mk):
    _, _, it = mk.tree()
    r = client.post(f"/api/items/{it['id']}/feedback", json={"outcome": "great"})
    assert r.status_code == 422 and "helped" in r.json()["detail"]
    assert client.post("/api/items/nope/feedback",
                       json={"outcome": "helped"}).status_code == 404


def test_rotas_antigas_de_ajuste_sumiram(client, mk):
    _, _, it = mk.tree()
    for path, body in (("confidence", {"value": 1}), ("importance", {"value": 1}),
                       ("memory_class", {"memory_class": "working"}),
                       ("labels", {"label_id": "x"})):
        assert client.put(f"/api/items/{it['id']}/{path}", json=body).status_code == 404
        assert client.get(f"/api/items/{it['id']}/{path}").status_code == 404


def test_datas_saem_com_z_e_sem_campos_do_modelo_antigo(client, mk):
    _, _, it = mk.tree()
    for d in (it, client.get(f"/api/items/{it['id']}").json(),
              client.get("/api/items").json()["items"][0]):
        for name in ("created_at", "updated_at"):
            assert d[name].endswith("Z") and len(d[name]) == len("2026-10-08T20:31:15Z"), d[name]
        assert "last_accessed" not in d and "access_count" not in d


def test_expires_e_verified_at_tambem_com_z(client, mk):
    ws = mk.ws("Z")
    pj = mk.project(ws["id"], "P")
    d = mk.item(ws["id"], pj["id"], "Com ttl", ttl_days=3)
    assert d["expires_at"].endswith("Z")


def test_id_inexistente_diz_qual_item_nao_foi_achado(client):
    r = client.get("/api/items/memory-class")
    assert r.status_code == 404 and r.json()["detail"] == "Item não encontrado: memory-class"
