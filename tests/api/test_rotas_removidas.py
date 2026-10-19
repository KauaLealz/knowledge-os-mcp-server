"""Rotas do modelo antigo não existem no v2: labels, ajustes de confidence/importance/
memory_class e as estatísticas soltas — todas 404."""

import pytest


@pytest.mark.parametrize("method,path", [
    ("get", "/api/labels"),
    ("post", "/api/labels"),
    ("delete", "/api/labels/x"),
    ("get", "/api/items/x/labels"),
    ("post", "/api/items/x/labels"),
    ("delete", "/api/items/x/labels/y"),
    ("put", "/api/items/x/confidence"),
    ("put", "/api/items/x/importance"),
    ("put", "/api/items/x/memory_class"),
    ("get", "/api/workspaces/x/stats"),
    ("get", "/api/projects/x/stats"),
])
def test_rota_antiga_e_404(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_openapi_nao_fala_do_modelo_antigo(client):
    text = client.get("/api/openapi.json").text
    for word in ("memory_class", "confidence", "importance", "labels", "label_id"):
        assert word not in text, word
