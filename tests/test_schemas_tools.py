"""Testes de schemas e registro de tools."""


import pytest
from pydantic import ValidationError as PydanticValidationError

from knowledge_os.schemas.project_schemas import ProjectCreate
from knowledge_os.schemas.workspace_schemas import WorkspaceCreate


def test_workspace_create_valida_nome():
    assert WorkspaceCreate(name="ok").description is None
    with pytest.raises(PydanticValidationError):
        WorkspaceCreate(name="")
    with pytest.raises(PydanticValidationError):
        WorkspaceCreate(name="x" * 256)


def test_project_create_valida_nome():
    with pytest.raises(PydanticValidationError):
        ProjectCreate(workspace_id="w", name="")




