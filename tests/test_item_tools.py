"""Testes do ItemService (CRUD) e dos schemas de item."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.schemas.item_schemas import ItemCreate, ItemSearchRequest
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.tag_service import TagService


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _kw(ws, dm, **over):
    base = dict(
        workspace_id=ws.id, project_id=dm.id, type="rule", memory_class="longterm",
        title="Titulo", summary="Resumo", content="Conteudo longo",
    )
    base.update(over)
    return base


class TestService:
    def test_create_com_tags_e_labels(self, svc, sample_workspace, sample_project):
        a = svc.create(
            **_kw(sample_workspace, sample_project, tags=["x", "y"], labels=["official"])
        )
        b = svc.create(**_kw(sample_workspace, sample_project, tags=["x"], labels=["official"]))
        assert a.tags == ["x", "y"]
        assert b.labels == ["official"]
        assert [t.name for t in TagService().list()] == ["x", "y"]

    def test_create_dedup_tags_repetidas(self, svc, sample_workspace, sample_project):
        it = svc.create(**_kw(sample_workspace, sample_project, tags=["x", "x", " x "]))
        assert it.tags == ["x"]

    def test_create_sem_key_vai_para_sem_key(self, svc, sample_workspace, sample_project):
        it = svc.create(**_kw(sample_workspace, sample_project))
        assert it.path == f"testworkspace/testproject/_sem-key/{it.id}.md"

    def test_ephemeral_exige_ttl(self, svc, sample_workspace, sample_project):
        with pytest.raises(ValidationError):
            svc.create(**_kw(sample_workspace, sample_project, memory_class="ephemeral"))
        it = svc.create(
            **_kw(sample_workspace, sample_project, memory_class="ephemeral", ttl_days=7)
        )
        assert it.ttl_days == 7

    @pytest.mark.parametrize("over", [
        {"memory_class": "bogus"}, {"type": "bogus"},
        {"confidence": 101}, {"importance": 11}, {"importance": -1},
    ])
    def test_create_invalido(self, svc, sample_workspace, sample_project, over):
        with pytest.raises(ValidationError):
            svc.create(**_kw(sample_workspace, sample_project, **over))

    def test_create_project_inexistente(self, svc, sample_workspace, sample_project):
        with pytest.raises(NotFoundError):
            svc.create(**_kw(sample_workspace, sample_project, project_id="nope"))

    def test_get_retorna_content_e_not_found(self, svc, sample_workspace, sample_project):
        it = svc.create(**_kw(sample_workspace, sample_project, tags=["t"]))
        got = svc.get(it.id)
        assert got.content == "Conteudo longo"
        assert got.tags == ["t"]
        with pytest.raises(NotFoundError):
            svc.get("nope")

    def test_update_campos_permitidos(self, svc, sample_workspace, sample_project):
        it = svc.create(**_kw(sample_workspace, sample_project))
        up = svc.update(it.id, summary="novo", confidence=50, importance=3)
        assert (up.summary, up.confidence, up.importance) == ("novo", 50, 3)
        assert up.content == "Conteudo longo"

    def test_update_rejeita_campo_desconhecido_e_ttl_ephemeral_nulo(
        self, svc, sample_workspace, sample_project
    ):
        it = svc.create(**_kw(sample_workspace, sample_project))
        with pytest.raises(ValidationError):
            svc.update(it.id, workspace_id="x")  # mover de workspace não é edição
        eph = svc.create(
            **_kw(sample_workspace, sample_project, memory_class="ephemeral", ttl_days=7)
        )
        with pytest.raises(ValidationError):
            svc.update(eph.id, ttl_days=None)
        with pytest.raises(NotFoundError):
            svc.update("nope", summary="x")

    def test_delete(self, svc, sample_workspace, sample_project, data_dir):
        it = svc.create(**_kw(sample_workspace, sample_project, tags=["t"], labels=["l"]))
        assert svc.delete(it.id) is True
        with pytest.raises(NotFoundError):
            svc.get(it.id)
        assert not (data_dir / it.path).exists()
        with pytest.raises(NotFoundError):
            svc.delete(it.id)

    def test_sem_conexao_da_erro_claro(self, _isolated_home):
        from knowledge_os.config import NO_CONNECTION_MESSAGE

        with pytest.raises(ValidationError) as exc:
            ItemService().search(None, None, "x")
        assert str(exc.value) == NO_CONNECTION_MESSAGE
        assert not (_isolated_home / "connections.json").exists()  # nada é criado


class TestSchemas:
    def test_ephemeral_sem_ttl(self):
        with pytest.raises(PydanticValidationError):
            ItemCreate(workspace_id="w", project_id="d", type="rule", memory_class="ephemeral",
                       title="t", summary="s", content="c")

    def test_limites(self):
        with pytest.raises(PydanticValidationError):
            ItemCreate(workspace_id="w", project_id="d", type="rule", memory_class="longterm",
                       title="t", summary="s", content="c", confidence=101)
        assert ItemSearchRequest(workspace_id="w", query="q").limit == 10
