"""Testes de RelationService e relation_tools."""

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.db.models import Item
from src.exceptions import NotFoundError, ValidationError
from src.schemas.relation_schemas import RelationCreate
from src.services.relation_service import RelationService


@pytest.fixture
def use_test_engine(monkeypatch, test_engine):
    """Faz os services sem sessão explícita usarem o engine de teste."""
    monkeypatch.setattr("src.services._common.get_engine", lambda: test_engine)


@pytest.fixture
def other_item(test_session, sample_item) -> Item:
    item = Item(
        id=str(uuid.uuid4()), workspace_id=sample_item.workspace_id,
        domain_id=sample_item.domain_id, type="rule", memory_class="working",
        title="Other", summary="s", content="c",
    )
    test_session.add(item)
    test_session.commit()
    return item


def test_create_and_list_both_directions(test_session, sample_item, other_item):
    svc = RelationService(test_session)
    rel = svc.create(sample_item.id, other_item.id, "depends_on")
    assert rel.id and rel.relation_type == "depends_on"
    assert [r.id for r in svc.list(sample_item.id)] == [rel.id]
    assert [r.id for r in svc.list(other_item.id)] == [rel.id]


@pytest.mark.parametrize(
    "rtype", ["related_to", "depends_on", "implements", "references", "supersedes", "derived_from"]
)
def test_all_valid_types(test_session, sample_item, other_item, rtype):
    assert RelationService(test_session).create(sample_item.id, other_item.id, rtype)


def test_invalid_type(test_session, sample_item, other_item):
    with pytest.raises(ValidationError):
        RelationService(test_session).create(sample_item.id, other_item.id, "likes")


def test_missing_item(test_session, sample_item):
    with pytest.raises(NotFoundError):
        RelationService(test_session).create(sample_item.id, "nope", "related_to")


def test_self_relation_rejected(test_session, sample_item):
    with pytest.raises(ValidationError):
        RelationService(test_session).create(sample_item.id, sample_item.id, "related_to")


def test_delete(test_session, sample_item, other_item):
    svc = RelationService(test_session)
    rel = svc.create(sample_item.id, other_item.id, "references")
    assert svc.delete(rel.id) is True
    assert svc.list(sample_item.id) == []
    with pytest.raises(NotFoundError):
        svc.delete(rel.id)


def test_schema_validates_type():
    with pytest.raises(PydanticValidationError):
        RelationCreate(source_item_id="a", target_item_id="b", relation_type="bad")


