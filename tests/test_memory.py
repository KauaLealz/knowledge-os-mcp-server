"""Testes de MemoryService."""

import pytest

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.memory_service import MemoryService


@pytest.fixture
def make(sample_workspace, sample_project):
    def _make(memory_class, ttl=None):
        return ItemService().create(
            workspace_id=sample_workspace.id, project_id=sample_project.id, type="knowledge",
            memory_class=memory_class, ttl_days=ttl, title="T", summary="s", content="c",
        )
    return _make


def test_promote_ephemeral_clears_ttl(make):
    it = make("ephemeral", 7)
    item = MemoryService().promote(it.id, "working")
    assert item.memory_class == "working" and item.ttl_days is None


def test_promote_chain(make):
    svc = MemoryService()
    it = make("working")
    assert svc.promote(it.id, "longterm").memory_class == "longterm"
    assert svc.promote(it.id, "canonical").memory_class == "canonical"
    eph = make("ephemeral", 15)
    assert svc.promote(eph.id, "canonical").ttl_days is None


def test_promote_to_ephemeral_rejected(sample_item):
    with pytest.raises(ValidationError):
        MemoryService().promote(sample_item.id, "ephemeral")


def test_promote_downgrade_or_same_rejected(sample_item):
    svc = MemoryService()  # sample_item é longterm
    with pytest.raises(ValidationError):
        svc.promote(sample_item.id, "working")
    with pytest.raises(ValidationError):
        svc.promote(sample_item.id, "longterm")


def test_promote_invalid_class_and_missing(sample_item):
    svc = MemoryService()
    with pytest.raises(ValidationError):
        svc.promote(sample_item.id, "bogus")
    with pytest.raises(NotFoundError):
        svc.promote("nope", "canonical")


def test_renew(make):
    it = make("ephemeral", 7)
    assert MemoryService().renew(it.id, 30).ttl_days == 30


def test_renew_rejects_non_ephemeral_and_bad_ttl(sample_item, make):
    svc = MemoryService()
    with pytest.raises(ValidationError):
        svc.renew(sample_item.id, 30)  # longterm
    eph = make("ephemeral", 7)
    with pytest.raises(ValidationError):
        svc.renew(eph.id, 0)
    with pytest.raises(NotFoundError):
        svc.renew("nope", 7)
