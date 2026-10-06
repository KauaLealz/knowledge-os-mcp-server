"""Fixtures da API: banco SQLite temporário isolado por teste."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from knowledge_os.api.deps import get_artifacts_dir, get_catalog_engine_dep, get_engine_dep
from knowledge_os.api.main import app
from knowledge_os.db.migrations import bootstrap_labels
from knowledge_os.db.session import create_db_engine, init_db


@pytest.fixture
def engine(tmp_path):
    eng = init_db(create_db_engine(f"sqlite:///{tmp_path / 'api.db'}"))
    with Session(eng) as s:
        bootstrap_labels(s)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine, tmp_path):
    art_dir = tmp_path / "artifacts"
    app.dependency_overrides[get_engine_dep] = lambda: engine
    app.dependency_overrides[get_catalog_engine_dep] = lambda: engine
    app.dependency_overrides[get_artifacts_dir] = lambda: art_dir
    yield TestClient(app)
    app.dependency_overrides.clear()


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
