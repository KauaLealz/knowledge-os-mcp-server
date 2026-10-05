"""Testes de MemoryService e memory_tools."""

import pytest

from src.exceptions import NotFoundError, ValidationError
from src.services.memory_service import MemoryService


@pytest.fixture
def use_test_engine(monkeypatch, test_engine):
    """Faz os services sem sessão explícita usarem o engine de teste."""
    monkeypatch.setattr("src.services._common.get_engine", lambda: test_engine)


def _set(session, item, memory_class, ttl=None):
    item.memory_class = memory_class
    item.ttl_days = ttl
    session.commit()


def test_promote_ephemeral_clears_ttl(test_session, sample_item):
    _set(test_session, sample_item, "ephemeral", 7)
    item = MemoryService(test_session).promote(sample_item.id, "working")
    assert item.memory_class == "working" and item.ttl_days is None


def test_promote_chain_and_skip(test_session, sample_item):
    svc = MemoryService(test_session)
    _set(test_session, sample_item, "working")
    assert svc.promote(sample_item.id, "longterm").memory_class == "longterm"
    assert svc.promote(sample_item.id, "canonical").memory_class == "canonical"
    _set(test_session, sample_item, "ephemeral", 15)
    assert svc.promote(sample_item.id, "canonical").ttl_days is None


def test_promote_to_ephemeral_rejected(test_session, sample_item):
    with pytest.raises(ValidationError):
        MemoryService(test_session).promote(sample_item.id, "ephemeral")


def test_promote_downgrade_or_same_rejected(test_session, sample_item):
    svc = MemoryService(test_session)  # sample_item é longterm
    with pytest.raises(ValidationError):
        svc.promote(sample_item.id, "working")
    with pytest.raises(ValidationError):
        svc.promote(sample_item.id, "longterm")


def test_promote_invalid_class_and_missing(test_session, sample_item):
    svc = MemoryService(test_session)
    with pytest.raises(ValidationError):
        svc.promote(sample_item.id, "bogus")
    with pytest.raises(NotFoundError):
        svc.promote("nope", "canonical")


def test_renew(test_session, sample_item):
    _set(test_session, sample_item, "ephemeral", 7)
    assert MemoryService(test_session).renew(sample_item.id, 30).ttl_days == 30


def test_renew_rejects_non_ephemeral_and_bad_ttl(test_session, sample_item):
    svc = MemoryService(test_session)
    with pytest.raises(ValidationError):
        svc.renew(sample_item.id, 30)  # longterm
    _set(test_session, sample_item, "ephemeral", 7)
    with pytest.raises(ValidationError):
        svc.renew(sample_item.id, 0)
    with pytest.raises(NotFoundError):
        svc.renew("nope", 7)


