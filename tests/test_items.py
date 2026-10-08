"""Tipos de item no `create` fino (a API usa): os 5 do v2 valem, os antigos não."""

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_service import ItemService


def _kw(**over):
    base = dict(workspace_id="W", project_id="P", type="context", title="Titulo",
                summary="Resumo", content="Conteudo")
    base.update(over)
    return base


@pytest.mark.parametrize("item_type", ["rule", "howto", "context", "spec"])
def test_item_create_tipos_v2(conn, item_type):
    item = ItemService().create(**_kw(type=item_type))
    assert item.type == item_type and item.origin == "agent"


@pytest.mark.parametrize("item_type", ["invalid_type", "task", "insight", "knowledge"])
def test_item_tipo_fora_do_v2_e_recusado(conn, item_type):
    with pytest.raises(ValidationError, match="Válidos: rule, howto, context, spec, secret"):
        ItemService().create(**_kw(type=item_type))
