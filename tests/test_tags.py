"""Testes de TagService e tag_tools."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text

from src.exceptions import NotFoundError, ValidationError
from src.mcp import tag_tools
from src.schemas.tag_schemas import TagCreate
from src.services.tag_service import TagService


def test_create_list_unique(test_session):
    svc = TagService(test_session)
    tag = svc.create("spring")
    assert tag.id
    assert [t.name for t in svc.list()] == ["spring"]
    with pytest.raises(ValidationError):
        svc.create("spring")


def test_empty_name_rejected(test_session):
    with pytest.raises(ValidationError):
        TagService(test_session).create("   ")


def test_delete_removes_from_items(test_session, test_engine, sample_item, sample_tag):
    sample_item.tags.append(sample_tag)
    test_session.commit()
    assert TagService(test_session).delete(sample_tag.id) is True
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM item_tags")).scalar() == 0
    test_session.refresh(sample_item)
    assert sample_item.tags == []
    with pytest.raises(NotFoundError):
        TagService(test_session).delete(sample_tag.id)


def test_schema_length():
    with pytest.raises(PydanticValidationError):
        TagCreate(name="x" * 101)
    with pytest.raises(PydanticValidationError):
        TagCreate(name="")


def test_tools(use_test_engine):
    created = tag_tools.tag_create("alpha")
    assert created["name"] == "alpha"
    assert [t["name"] for t in tag_tools.tag_list()] == ["alpha"]
    assert tag_tools.tag_delete(created["id"])["status"] == "ok"
    assert tag_tools.tag_list() == []
