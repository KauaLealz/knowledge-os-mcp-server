"""Testes da validação de tipos de item."""

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_service import ItemService


def _kw(ws, dm, **over):
    base = dict(
        workspace_id=ws.id, project_id=dm.id, type="context", memory_class="working",
        title="Titulo", summary="Resumo", content="Conteudo",
    )
    base.update(over)
    return base


def test_item_create_valid_type(sample_workspace, sample_project):
    item = ItemService().create(**_kw(sample_workspace, sample_project))
    assert item.type == "context"
    assert item.memory_class in ("working", "longterm")


def test_item_type_invalid(sample_workspace, sample_project):
    """Tipo inválido é rejeitado."""
    with pytest.raises(ValidationError):
        ItemService().create(**_kw(sample_workspace, sample_project, type="invalid_type"))


def test_item_type_task_nao_existe_mais(sample_workspace, sample_project):
    """`task` foi removido do conjunto de tipos válidos."""
    with pytest.raises(ValidationError):
        ItemService().create(**_kw(sample_workspace, sample_project, type="task"))


def test_item_type_spec_e_valido(sample_workspace, sample_project):
    """`spec` é o novo tipo para especificações/planos de mudança."""
    item = ItemService().create(**_kw(sample_workspace, sample_project, type="spec"))
    assert item.type == "spec"
