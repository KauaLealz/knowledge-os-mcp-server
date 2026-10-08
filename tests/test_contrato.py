"""Contrato da superfície MCP (V2_MVP.md §11): exatamente 32 ferramentas, docstrings com uso,
retorno e exemplo, instruções geradas da taxonomia e toda ferramenta citada nos textos existe."""

import asyncio
import re
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

from knowledge_os import model
from knowledge_os.mcp import tools
from knowledge_os.mcp.instructions import build_instructions

ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS = ROOT / "src" / "knowledge_os" / "mcp" / "INSTRUCTIONS.md"

ORG = ("list", "create", "update", "merge", "delete")
EXPECTED = {
    *(f"{kind}_{op}" for kind in ("workspace", "project", "subject") for op in ORG),
    "repo",
    "item_search", "item_get", "item_save", "item_delete", "item_feedback", "item_graph",
    "relation_create", "relation_delete",
    "tag_list", "tag_create", "tag_update", "tag_delete",
    "connection_create", "connection_list", "connection_delete",
    "health_check",
}
GONE = {"context_get", "label_list", "label_create", "label_delete", "workspace_rename",
        "project_rename", "subject_rename"}

# Identificadores com cara de ferramenta; parâmetros que casam o mesmo padrão ficam de fora.
_TOOLISH = re.compile(
    r"\b((?:workspace|project|subject|item|relation|tag|connection|label|context|health)"
    r"_[a-z]+(?:_[a-z]+)*)\b"
)
_PARAMS = {"relation_types", "item_ids", "connection_id", "workspace_id", "project_id",
           "subject_id", "item_id", "tag_names", "context_head"}


def cited_tools(text: str) -> set[str]:
    return {n for n in _TOOLISH.findall(text) if n not in _PARAMS and not n.endswith("_id")}


def registered() -> dict[str, str]:
    server = FastMCP(name="contrato")
    tools.register(server)

    async def run() -> dict[str, str]:
        async with Client(server) as client:
            return {t.name: t.description or "" for t in await client.list_tools()}

    return asyncio.run(run())


def test_exatamente_as_32_ferramentas():
    names = set(registered())
    assert len(EXPECTED) == 32
    assert names == EXPECTED
    assert not names & GONE


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_docstring_tem_uso_retorno_e_exemplo(name):
    doc = registered()[name]
    for part in ("**Use quando:**", "**Retorna:**", "**Exemplo:**"):
        assert part in doc, f"{name}: falta {part}"


def test_ferramentas_com_connection_id():
    """Todas aceitam `connection_id`, menos `connection_*` e `health_check`."""
    server = FastMCP(name="contrato")
    tools.register(server)
    listed = asyncio.run(server.list_tools())
    for tool in listed:
        props = set((tool.parameters or {}).get("properties", {}))
        if tool.name.startswith("connection_") or tool.name == "health_check":
            assert "connection_id" not in props, tool.name
        else:
            assert "connection_id" in props, tool.name


def test_item_save_lista_campos_e_valores_do_modelo():
    doc = registered()["item_save"]
    for field in model.ITEM_FIELDS + model.LOCATION_FIELDS:
        assert f"`{field}`" in doc, field
    for value in (*model.TYPES, *model.STATUSES, *model.SPEC_STATUSES, *model.SCOPES,
                  *model.ORIGINS):
        assert value in doc, value
    for subs in model.TYPES.values():
        for sub in subs:
            assert sub in doc, sub


def test_instructions_md_e_gerado():
    assert INSTRUCTIONS.read_text(encoding="utf-8") == build_instructions()
    assert model.taxonomy_markdown() in build_instructions()


def test_instructions_citam_so_ferramentas_que_existem():
    cited = cited_tools(INSTRUCTIONS.read_text(encoding="utf-8"))
    assert cited, "as instruções deveriam citar ferramentas"
    assert cited <= EXPECTED, cited - EXPECTED


@pytest.mark.xfail(strict=False, reason="README e MCP_USAGE são reescritos na fase 8")
@pytest.mark.parametrize("doc", ["README.md", "docs/MCP_USAGE.md"])
def test_docs_citam_so_ferramentas_que_existem(doc):
    cited = cited_tools((ROOT / doc).read_text(encoding="utf-8"))
    assert cited <= EXPECTED, cited - EXPECTED


@pytest.mark.xfail(strict=False, reason="MCP_USAGE é reescrito na fase 8")
def test_mcp_usage_cita_toda_ferramenta_registrada():
    text = (ROOT / "docs" / "MCP_USAGE.md").read_text(encoding="utf-8")
    assert EXPECTED <= cited_tools(text) | ({"repo"} if "repo(" in text else set())
