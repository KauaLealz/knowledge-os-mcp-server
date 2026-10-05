"""Testes de schemas e registro de tools."""


import pytest
from pydantic import ValidationError as PydanticValidationError

from src.schemas.domain_schemas import DomainCreate
from src.schemas.workspace_schemas import WorkspaceCreate


def test_workspace_create_valida_nome():
    assert WorkspaceCreate(name="ok").description is None
    with pytest.raises(PydanticValidationError):
        WorkspaceCreate(name="")
    with pytest.raises(PydanticValidationError):
        WorkspaceCreate(name="x" * 256)


def test_domain_create_valida_nome():
    with pytest.raises(PydanticValidationError):
        DomainCreate(workspace_id="w", name="")




