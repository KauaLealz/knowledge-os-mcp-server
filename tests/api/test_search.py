"""Busca pela API (v6): a resposta é a do `ItemService.search` (resultados explicados, nunca o
`content`), com os ids para montar o link na UI. Filtros: types, tags, paths (sem
subtype/scope/status/origin)."""

RESULT_FIELDS = {"id", "key", "type", "title", "summary", "where", "score", "matched_in",
                 "snippet", "workspace_id", "project_id", "subject_id"}


def _search(client, **params):
    r = client.get("/api/items/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_search_devolve_o_formato_do_servico(client, mk):
    ws, dm, it = mk.tree()
    body = _search(client, query="conditional")
    assert set(body) == {"results"}
    (hit,) = body["results"]
    assert RESULT_FIELDS <= hit.keys()
    assert "content" not in hit and "subtype" not in hit and "scope" not in hit
    assert hit["id"] == it["id"] and hit["where"] == "WS/Dom"
    assert (hit["workspace_id"], hit["project_id"]) == (ws["id"], dm["id"])
    assert "summary" in hit["matched_in"]


def test_search_no_match(client, mk):
    mk.tree()
    assert _search(client, query="zzzinexistente")["results"] == []


def test_search_everywhere_ve_todos_os_workspaces(client, mk):
    ws, dm, _ = mk.tree()
    other = mk.ws("Outro WS")
    pj = mk.project(other["id"], "P")
    mk.item(other["id"], pj["id"], "Fora conditional")
    every = {h["title"] for h in _search(client, query="conditional")["results"]}
    assert every == {"Item", "Fora conditional"}
    so_ws = {h["title"] for h in _search(client, query="conditional",
                                         workspace_id=ws["id"])["results"]}
    assert so_ws == {"Item"}


def test_search_project_e_subject(client, mk):
    ws, dm, _ = mk.tree()
    dm2 = mk.project(ws["id"], "Dom2")
    mk.item(ws["id"], dm2["id"], "Other conditional")
    sj = mk.subject(ws["id"], dm2["id"], "Pix")
    mk.item(ws["id"], dm2["id"], "Pix conditional", subject_id=sj["id"])

    def titles(**params):
        return sorted(h["title"] for h in _search(client, query="conditional",
                                                  workspace_id=ws["id"], **params)["results"])

    assert titles(project_id=dm2["id"]) == ["Other conditional", "Pix conditional"]
    assert titles(project_id=f"{dm['id']},{dm2['id']}") == [
        "Item", "Other conditional", "Pix conditional"]
    assert titles(subject_id=sj["id"]) == ["Pix conditional"]


def test_search_filtros_v6(client, mk):
    ws, dm, _ = mk.tree()
    mk.item(ws["id"], dm["id"], "Howto conditional", type="howto", tags=["deploy", "procedure"])
    mk.item(ws["id"], dm["id"], "Ctx conditional", type="context", tags=["stack"])

    def titles(**params):
        return sorted(h["title"] for h in _search(client, query="conditional",
                                                  workspace_id=ws["id"], **params)["results"])

    assert titles(types="howto") == ["Howto conditional"]
    assert titles(tags="deploy") == ["Howto conditional"]
    assert titles(tags="stack") == ["Ctx conditional"]


def test_search_filtro_invalido_e_422_com_os_validos(client, mk):
    mk.tree()
    r = client.get("/api/items/search", params={"query": "x", "types": "insight"})
    assert r.status_code == 422 and "Válidos" in r.json()["detail"]
    r = client.get("/api/items/search", params={"query": "x", "labels": "a"})
    assert r.status_code == 422


def test_search_limit_ate_50(client):
    assert client.get("/api/items/search", params={"query": "x", "limit": 51}).status_code == 422


def test_search_unknown_workspace_is_404(client):
    r = client.get("/api/items/search", params={"query": "x", "workspace_id": "nope"})
    assert r.status_code == 404
