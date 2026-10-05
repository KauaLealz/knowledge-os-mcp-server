"""Testes de schemas e registro de tools."""


import pytest
from fastmcp import FastMCP
from pydantic import ValidationError as PydanticValidationError

from src.exceptions import NotFoundError
from src.mcp import domain_tools, workspace_tools
from src.schemas.domain_schemas import DomainCreate
from src.schemas.workspace_schemas import WorkspaceCreate
from tests.helpers_mcp import run_tool, tools_by_name


def test_workspace_create_valida_nome():
    assert WorkspaceCreate(name="ok").description is None
    with pytest.raises(PydanticValidationError):
        WorkspaceCreate(name="")
    with pytest.raises(PydanticValidationError):
        WorkspaceCreate(name="x" * 256)


def test_domain_create_valida_nome():
    with pytest.raises(PydanticValidationError):
        DomainCreate(workspace_id="w", name="")


def test_12_tools_registrados():
    m = FastMCP(name="t")
    workspace_tools.register(m)
    domain_tools.register(m)
    names = set(tools_by_name(m))
    assert names == {
        f"{p}_{a}"
        for p in ("workspace", "domain")
        for a in ("create", "list", "get", "delete", "export", "import")
    }


def test_fluxo_tools_ponta_a_ponta(test_engine, monkeypatch):
    monkeypatch.setattr("src.services._common.get_engine", lambda: test_engine)
    m = FastMCP(name="t")
    workspace_tools.register(m)
    domain_tools.register(m)

    def call(name: str, args: dict):
        return run_tool(m, name, args)

    call("workspace_create", {"name": "w1"})
    call("domain_create", {"workspace": "w1", "name": "d1"})
    assert "d1" in call("domain_get", {"workspace": "w1", "name": "d1"})[0].text
    assert call("workspace_delete", {"name": "w1"})[0].text
    assert "not_found" in call("workspace_delete", {"name": "w1"})[0].text
    with pytest.raises(NotFoundError):
        call("workspace_get", {"name": "w1"})
    with pytest.raises(NotFoundError):
        call("workspace_import", {"file_path": "arquivo-inexistente.zip"})
