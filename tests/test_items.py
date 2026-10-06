"""Testes do tipo de item `task` e da validação de tipos."""

import pytest
from sqlalchemy import Engine

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_service import ItemService


def _kw(ws, dm, **over):
    base = dict(
        workspace_id=ws.id, project_id=dm.id, type="task", memory_class="working",
        title="Titulo", summary="Resumo", content="Conteudo",
    )
    base.update(over)
    return base


def test_item_create_task_type(test_engine: Engine, sample_workspace, sample_project):
    """task é um tipo válido de item."""
    item = ItemService(test_engine).create(**_kw(sample_workspace, sample_project))
    assert item.type == "task"
    assert item.memory_class in ("working", "longterm")


def test_item_type_invalid(test_engine: Engine, sample_workspace, sample_project):
    """Tipo inválido é rejeitado."""
    with pytest.raises(ValidationError):
        ItemService(test_engine).create(
            **_kw(sample_workspace, sample_project, type="invalid_type")
        )
