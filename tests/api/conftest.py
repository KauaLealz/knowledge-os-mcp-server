"""Fixtures da API: uma conexão padrão sobre uma pasta temporária, isolada por teste."""

import pytest
from fastapi.testclient import TestClient

from knowledge_os.api.main import app


@pytest.fixture
def client(conn):
    yield TestClient(app)


@pytest.fixture
def mk(client):
    """Fábricas de recursos via API."""

    class Maker:
        def ws(self, name="WS", description=None):
            r = client.post(
                "/api/workspaces", json={"name": name, "description": description}
            )
            assert r.status_code == 201, r.text
            return r.json()

        def project(self, ws_id, name="Dom"):
            r = client.post(
                "/api/projects", json={"workspace_id": ws_id, "name": name}
            )
            assert r.status_code == 201, r.text
            return r.json()

        def item(self, ws_id, dom_id, title="Item", **extra):
            body = {
                "workspace_id": ws_id, "project_id": dom_id, "type": "knowledge",
                "memory_class": "longterm", "title": title,
                "summary": f"Resumo {title} conditional", "content": f"Conteudo {title}",
            }
            body.update(extra)
            r = client.post("/api/items", json=body)
            assert r.status_code == 201, r.text
            return r.json()

        def tree(self):
            ws = self.ws()
            dm = self.project(ws["id"])
            return ws, dm, self.item(ws["id"], dm["id"])

    return Maker()
