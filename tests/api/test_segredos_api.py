"""Valor de segredo pela API da UI: grava e apaga, nunca devolve, nunca ecoa."""

VALUE = "npm_Zx81kQ2pL0aVb7Yt3Rw9Mn4C"


def test_api_define_e_apaga_o_valor_sem_nunca_devolver(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    it = mk.item(ws["id"], dm["id"], type="secret", title="Token")
    assert it["has_value"] is False
    r = client.put(f"/api/items/{it['id']}/secret", json={"value": VALUE})
    assert r.status_code == 204
    for url in (f"/api/items/{it['id']}", "/api/items", f"/api/workspaces/{ws['id']}/tree",
                "/api/items/search?query=Token"):
        r = client.get(url)
        assert r.status_code == 200 and VALUE not in r.text, url
    assert client.get(f"/api/items/{it['id']}").json()["has_value"] is True
    assert client.delete(f"/api/items/{it['id']}/secret").status_code == 204
    assert client.get(f"/api/items/{it['id']}").json()["has_value"] is False


def test_api_erro_de_validacao_nao_ecoa_o_valor(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    it = mk.item(ws["id"], dm["id"], type="secret", title="Token")
    big = VALUE * 5000
    r = client.put(f"/api/items/{it['id']}/secret", json={"value": big})
    assert r.status_code == 422 and VALUE not in r.text
    r = client.put(f"/api/items/{it['id']}/secret", json={"value": 123})
    assert r.status_code == 422
    regra = mk.item(ws["id"], dm["id"], type="rule", title="Regra")
    r = client.put(f"/api/items/{regra['id']}/secret", json={"value": VALUE})
    assert r.status_code == 422 and VALUE not in r.text


def test_api_escrita_de_outra_origem_e_recusada(client, mk):
    ws = mk.ws()
    dm = mk.project(ws["id"])
    it = mk.item(ws["id"], dm["id"], type="secret", title="Token")
    r = client.put(f"/api/items/{it['id']}/secret", json={"value": VALUE},
                   headers={"Origin": "http://evil.test"})
    assert r.status_code == 403
