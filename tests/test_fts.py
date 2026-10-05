"""Testes da busca FTS5 do ItemService."""

import pytest
from sqlalchemy import Engine

from src.db.models import Domain, Item, Workspace
from src.exceptions import ValidationError
from src.services.item_service import ItemService


@pytest.fixture
def svc(test_engine: Engine) -> ItemService:
    """ItemService ligado ao engine em memória."""
    return ItemService(test_engine)


def _mk(svc: ItemService, ws: Workspace, dm: Domain, **kw) -> Item:
    base = dict(
        workspace_id=ws.id, domain_id=dm.id, type="knowledge", memory_class="longterm",
        title="t", summary="s", content="c",
    )
    base.update(kw)
    return svc.create(**base)


def test_search_nao_retorna_content(svc, sample_workspace, sample_domain):
    _mk(svc, sample_workspace, sample_domain, title="Spring", summary="beans",
        content="ConditionalOnProperty detalhado")
    res = svc.search(sample_workspace.id, None, "ConditionalOnProperty")
    assert len(res) == 1
    assert set(res[0]) == {
        "id", "key", "type", "memory_class", "domain", "title", "summary", "score", "uses"}
    assert "content" not in res[0]
    assert isinstance(res[0]["score"], float)


def test_search_ordena_por_importance_desc(svc, sample_workspace, sample_domain):
    a = _mk(svc, sample_workspace, sample_domain, title="a", content="kafka", importance=2)
    b = _mk(svc, sample_workspace, sample_domain, title="b", content="kafka", importance=9)
    res = svc.search(sample_workspace.id, None, "kafka")
    assert [r["id"] for r in res] == [b.id, a.id]


def test_search_filtros_types_e_memory_classes(svc, sample_workspace, sample_domain):
    _mk(svc, sample_workspace, sample_domain, type="rule", content="redis")
    k = _mk(svc, sample_workspace, sample_domain, type="knowledge",
            memory_class="canonical", content="redis")
    res = svc.search(sample_workspace.id, None, "redis", types=["knowledge"],
                     memory_classes=["canonical"])
    assert [r["id"] for r in res] == [k.id]


def test_search_filtra_por_domain_e_workspace(svc, test_session, sample_workspace, sample_domain):
    other = Domain(id="dm_other", workspace_id=sample_workspace.id, name="Other")
    test_session.add(other)
    test_session.commit()
    _mk(svc, sample_workspace, sample_domain, content="helm")
    o = _mk(svc, sample_workspace, other, content="helm")
    res = svc.search(sample_workspace.id, other.id, "helm")
    assert [r["id"] for r in res] == [o.id]
    assert svc.search("ws_inexistente", None, "helm") == []


def test_search_incrementa_access_count(svc, sample_workspace, sample_domain):
    it = _mk(svc, sample_workspace, sample_domain, content="grafana")
    assert it.access_count in (0, None)
    svc.search(sample_workspace.id, None, "grafana")
    svc.search(sample_workspace.id, None, "grafana")
    got = svc.get(it.id)
    assert got.access_count == 2
    assert got.last_accessed is not None


def test_search_limit(svc, sample_workspace, sample_domain):
    for i in range(5):
        _mk(svc, sample_workspace, sample_domain, title=f"n{i}", content="nginx")
    assert len(svc.search(sample_workspace.id, None, "nginx", limit=3)) == 3


def test_search_reflete_update(svc, sample_workspace, sample_domain):
    it = _mk(svc, sample_workspace, sample_domain, content="antigo")
    svc.update(it.id, content="novissimo")
    assert svc.search(sample_workspace.id, None, "antigo") == []
    assert len(svc.search(sample_workspace.id, None, "novissimo")) == 1


def test_search_query_vazia_lista_sem_fts(svc, sample_workspace, sample_domain):
    _mk(svc, sample_workspace, sample_domain)
    assert len(svc.search(sample_workspace.id, None, "")) == 1


def test_search_sintaxe_fts_invalida(svc, sample_workspace, sample_domain):
    _mk(svc, sample_workspace, sample_domain)
    with pytest.raises(ValidationError):
        svc.search(sample_workspace.id, None, '"aberta')
