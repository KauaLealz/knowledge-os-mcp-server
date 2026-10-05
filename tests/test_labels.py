"""Testes de LabelService e label_tools."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text

from src.exceptions import NotFoundError, ValidationError
from src.schemas.label_schemas import LabelCreate
from src.services.label_service import LabelService


@pytest.fixture
def use_test_engine(monkeypatch, test_engine):
    """Faz os services sem sessão explícita usarem o engine de teste."""
    monkeypatch.setattr("src.services._common.get_engine", lambda: test_engine)


def test_create_list_unique(test_session):
    svc = LabelService(test_session)
    label = svc.create("gold")
    assert label.id
    assert [x.name for x in svc.list()] == ["gold"]
    with pytest.raises(ValidationError):
        svc.create("gold")


def test_empty_name_rejected(test_session):
    with pytest.raises(ValidationError):
        LabelService(test_session).create("   ")


def test_delete_removes_from_items(test_session, test_engine, sample_item, sample_label):
    sample_item.labels.append(sample_label)
    test_session.commit()
    assert LabelService(test_session).delete(sample_label.id) is True
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM item_labels")).scalar() == 0
    test_session.refresh(sample_item)
    assert sample_item.labels == []
    with pytest.raises(NotFoundError):
        LabelService(test_session).delete(sample_label.id)


def test_schema_length():
    with pytest.raises(PydanticValidationError):
        LabelCreate(name="x" * 101)
    with pytest.raises(PydanticValidationError):
        LabelCreate(name="")


