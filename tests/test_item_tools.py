"""Testes do ItemService (CRUD), schemas e tools MCP de item."""


import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, text

from src.exceptions import NotFoundError, ValidationError
from src.schemas.item_schemas import ItemCreate, ItemSearchRequest
from src.services.item_service import ItemService


@pytest.fixture
def svc(test_engine: Engine) -> ItemService:
    return ItemService(test_engine)


def _kw(ws, dm, **over):
    base = dict(
        workspace_id=ws.id, domain_id=dm.id, type="rule", memory_class="longterm",
        title="Titulo", summary="Resumo", content="Conteudo longo",
    )
    base.update(over)
    return base


class TestService:
    def test_create_com_tags_e_labels_reusa_existentes(
        self, svc, test_engine, sample_workspace, sample_domain
    ):
        a = svc.create(**_kw(sample_workspace, sample_domain, tags=["x", "y"], labels=["official"]))
        b = svc.create(**_kw(sample_workspace, sample_domain, tags=["x"], labels=["official"]))
        assert sorted(t.name for t in a.tags) == ["x", "y"]
        assert [lb.name for lb in b.labels] == ["official"]
        with test_engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM tags")).scalar() == 2
            assert c.execute(text("SELECT count(*) FROM labels")).scalar() == 1
            assert c.execute(text("SELECT count(*) FROM item_tags")).scalar() == 3

    def test_create_dedup_tags_repetidas(self, svc, sample_workspace, sample_domain):
        it = svc.create(**_kw(sample_workspace, sample_domain, tags=["x", "x"]))
        assert [t.name for t in it.tags] == ["x"]

    def test_ephemeral_exige_ttl(self, svc, sample_workspace, sample_domain):
        with pytest.raises(ValidationError):
            svc.create(**_kw(sample_workspace, sample_domain, memory_class="ephemeral"))
        it = svc.create(
            **_kw(sample_workspace, sample_domain, memory_class="ephemeral", ttl_days=7)
        )
        assert it.ttl_days == 7

    @pytest.mark.parametrize("over", [
        {"memory_class": "bogus"}, {"type": "bogus"},
        {"confidence": 101}, {"importance": 11}, {"importance": -1},
    ])
    def test_create_invalido(self, svc, sample_workspace, sample_domain, over):
        with pytest.raises(ValidationError):
            svc.create(**_kw(sample_workspace, sample_domain, **over))

    def test_create_domain_inexistente(self, svc, sample_workspace, sample_domain):
        with pytest.raises(NotFoundError):
            svc.create(**_kw(sample_workspace, sample_domain, domain_id="nope"))

    def test_get_retorna_content_e_not_found(self, svc, sample_workspace, sample_domain):
        it = svc.create(**_kw(sample_workspace, sample_domain, tags=["t"]))
        got = svc.get(it.id)
        assert got.content == "Conteudo longo"
        assert [t.name for t in got.tags] == ["t"]
        with pytest.raises(NotFoundError):
            svc.get("nope")

    def test_update_campos_permitidos(self, svc, sample_workspace, sample_domain):
        it = svc.create(**_kw(sample_workspace, sample_domain))
        up = svc.update(it.id, summary="novo", confidence=50, importance=3)
        assert (up.summary, up.confidence, up.importance) == ("novo", 50, 3)
        assert up.content == "Conteudo longo"

    def test_update_rejeita_campo_desconhecido_e_ttl_ephemeral_nulo(
        self, svc, sample_workspace, sample_domain
    ):
        it = svc.create(**_kw(sample_workspace, sample_domain))
        with pytest.raises(ValidationError):
            svc.update(it.id, workspace_id="x")  # mover de workspace não é edição
        eph = svc.create(
            **_kw(sample_workspace, sample_domain, memory_class="ephemeral", ttl_days=7)
        )
        with pytest.raises(ValidationError):
            svc.update(eph.id, ttl_days=None)
        with pytest.raises(NotFoundError):
            svc.update("nope", summary="x")

    def test_delete(self, svc, test_engine, sample_workspace, sample_domain):
        it = svc.create(**_kw(sample_workspace, sample_domain, tags=["t"], labels=["l"]))
        assert svc.delete(it.id) is True
        with pytest.raises(NotFoundError):
            svc.get(it.id)
        with test_engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM item_tags")).scalar() == 0
            assert c.execute(text("SELECT count(*) FROM item_labels")).scalar() == 0
        with pytest.raises(NotFoundError):
            svc.delete(it.id)


class TestSchemas:
    def test_ephemeral_sem_ttl(self):
        with pytest.raises(PydanticValidationError):
            ItemCreate(workspace_id="w", domain_id="d", type="rule", memory_class="ephemeral",
                       title="t", summary="s", content="c")

    def test_limites(self):
        with pytest.raises(PydanticValidationError):
            ItemCreate(workspace_id="w", domain_id="d", type="rule", memory_class="longterm",
                       title="t", summary="s", content="c", confidence=101)
        assert ItemSearchRequest(workspace_id="w", query="q").limit == 10


