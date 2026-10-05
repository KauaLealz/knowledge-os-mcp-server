"""MCP tools: labels."""

import logging
from typing import Any

from fastmcp import FastMCP

from src.schemas.label_schemas import LabelCreate, LabelListResponse, LabelResponse
from src.services.label_service import LabelService

logger = logging.getLogger(__name__)


def label_create(name: str, connection_id: str | None = None) -> dict[str, Any]:
    """Cria uma label (etiqueta controlada) no catálogo da connection.

    **Use quando:** Adicionar uma categoria formal além das padrão.
    **Retorna:** {id, name}.
    **Exemplo:** label_create(name="needs-review")
    **Notas:** Padrão do sistema: official, critical, experimental, deprecated, reference. Labels
        são uma lista controlada: crie com parcimônia. connection_id: opcional; sem ele usa a
        connection default (`default`).
    """
    req = LabelCreate(name=name)
    label = LabelService(connection_id=connection_id).create(req.name)
    return LabelResponse.model_validate(label).model_dump(mode="json")


def label_list(connection_id: str | None = None) -> list[dict[str, Any]]:
    """Lista todas as labels da connection.

    **Use quando:** Ver quais labels existem antes de usá-las em item_create.
    **Retorna:** Lista de {id, name}.
    **Exemplo:** label_list()
    **Notas:** connection_id: opcional; sem ele usa a connection default (`default`).
    """
    labels = LabelService(connection_id=connection_id).list()
    return LabelListResponse.model_validate(labels, from_attributes=True).model_dump(mode="json")


def label_delete(label_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Deleta uma label e a remove de todos os items.

    **Use quando:** Aposentar uma categoria controlada.
    **Retorna:** {status: ok, message}.
    **Exemplo:** label_delete(label_id="label_123")
    **Notas:** Os items permanecem. connection_id: opcional; sem ele usa a connection default
        (`default`).
    """
    LabelService(connection_id=connection_id).delete(label_id)
    return {"status": "ok", "message": f"Label removida: {label_id}"}


def register(mcp: FastMCP) -> None:
    """Registra as 3 tools de label no FastMCP."""
    for fn in (label_create, label_list, label_delete):
        mcp.tool()(fn)
