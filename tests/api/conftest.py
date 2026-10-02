"""Fixtures da API: banco SQLite temporário isolado por teste."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api import auth as auth_mod
from src.api.deps import get_artifacts_dir, get_engine_dep
from src.api.main import app
from src.db.migrations import bootstrap_labels
from src.db.session import create_db_engine, init_db


@pytest.fixture
def engine(tmp_path):
    eng = init_db(create_db_engine(f"sqlite:///{tmp_path / 'api.db'}"))
    with Session(eng) as s:
        bootstrap_labels(s)
    yield eng
    eng.dispose()


@pytest.fixture
def token():
    return "test-token"


@pytest.fixture
def client(engine, tmp_path, token):
    art_dir = tmp_path / "artifacts"
    app.dependency_overrides[get_engine_dep] = lambda: engine
    app.dependency_overrides[get_artifacts_dir] = lambda: art_dir
    auth_mod.set_token(token)
    yield TestClient(app)
    auth_mod.set_token(None)
    app.dependency_overrides.clear()


@pytest.fixture
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mk(client, auth):
    """Fábricas de recursos via API."""

    class Maker:
        def ws(self, name="WS", description=None):
            r = client.post(
                "/api/workspaces", json={"name": name, "description": description}, headers=auth
            )
            assert r.status_code == 201, r.text
            return r.json()

        def domain(self, ws_id, name="Dom"):
            r = client.post(
                "/api/domains", json={"workspace_id": ws_id, "name": name}, headers=auth
            )
            assert r.status_code == 201, r.text
            return r.json()

        def item(self, ws_id, dom_id, title="Item", **extra):
            body = {
                "workspace_id": ws_id, "domain_id": dom_id, "type": "knowledge",
                "memory_class": "longterm", "title": title,
                "summary": f"Resumo {title} conditional", "content": f"Conteudo {title}",
            }
            body.update(extra)
            r = client.post("/api/items", json=body, headers=auth)
            assert r.status_code == 201, r.text
            return r.json()

        def tree(self):
            ws = self.ws()
            dm = self.domain(ws["id"])
            return ws, dm, self.item(ws["id"], dm["id"])

    return Maker()
