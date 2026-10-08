"""Testes de RelationService (relações no frontmatter do item de origem)."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.schemas.relation_schemas import RelationCreate
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.relation_service import RelationService


@pytest.fixture
def other_item(sample_item):
    return ItemService().create(
        workspace_id=sample_item.workspace_id, project_id=sample_item.project_id,
        type="rule", memory_class="working", title="Other", summary="s", content="c",
        key="regra/other",
    )


def test_create_and_list_both_directions(sample_item, other_item):
    svc = RelationService()
    rel = svc.create(sample_item.id, other_item.id, "depends_on")
    assert rel.id and rel.relation_type == "depends_on"
    assert [r.id for r in svc.list(sample_item.id)] == [rel.id]
    assert [r.id for r in svc.list(other_item.id)] == [rel.id]


def test_relacao_fica_no_arquivo_da_origem_pela_key(sample_item, other_item, data_dir):
    RelationService().create(sample_item.id, other_item.id, "depends_on")
    text = (data_dir / ItemService().get(sample_item.id).path).read_text(encoding="utf-8")
    assert "type: depends_on" in text and "target: regra/other" in text


def test_id_da_relacao_e_estavel(sample_item, other_item):
    a = RelationService().create(sample_item.id, other_item.id, "references")
    b = RelationService().create(sample_item.id, other_item.id, "references")
    assert a.id == b.id
    assert len(RelationService().list(sample_item.id)) == 1


@pytest.mark.parametrize(
    "rtype", ["related_to", "depends_on", "implements", "references", "supersedes", "derived_from"]
)
def test_all_valid_types(sample_item, other_item, rtype):
    assert RelationService().create(sample_item.id, other_item.id, rtype)


def test_invalid_type(sample_item, other_item):
    with pytest.raises(ValidationError):
        RelationService().create(sample_item.id, other_item.id, "likes")


def test_missing_item(sample_item):
    with pytest.raises(NotFoundError):
        RelationService().create(sample_item.id, "nope", "related_to")


def test_self_relation_rejected(sample_item):
    with pytest.raises(ValidationError):
        RelationService().create(sample_item.id, sample_item.id, "related_to")


def test_delete(sample_item, other_item):
    svc = RelationService()
    rel = svc.create(sample_item.id, other_item.id, "references")
    assert svc.delete(rel.id) is True
    assert svc.list(sample_item.id) == []
    with pytest.raises(NotFoundError):
        svc.delete(rel.id)


def test_apagar_o_alvo_tira_a_relacao_da_origem(sample_item, other_item, data_dir):
    RelationService().create(sample_item.id, other_item.id, "references")
    ItemService().delete(other_item.id)
    assert RelationService().list(sample_item.id) == []
    text = (data_dir / ItemService().get(sample_item.id).path).read_text(encoding="utf-8")
    assert "relations: []" in text


def test_mover_o_alvo_de_project_troca_a_key_pelo_id(sample_item, other_item, data_dir):
    RelationService().create(sample_item.id, other_item.id, "references")
    ItemService().save([{"id": other_item.id, "workspace": "Outro", "project": "longe"}])
    (rel,) = RelationService().list(sample_item.id)
    assert rel.target_item_id == other_item.id
    text = (data_dir / ItemService().get(sample_item.id).path).read_text(encoding="utf-8")
    assert f"target: {other_item.id}" in text


def test_schema_validates_type():
    with pytest.raises(PydanticValidationError):
        RelationCreate(source_item_id="a", target_item_id="b", relation_type="bad")
