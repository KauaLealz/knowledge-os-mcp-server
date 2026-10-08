"""TagService: persistência no `.knowledge.yaml` da raiz, tag por item (API) e schema.

O contrato v2 (contagem, renomear/mesclar, remover, ensure_in_draft) está em test_tags_v2.py.
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from knowledge_os.exceptions import NotFoundError
from knowledge_os.schemas.tag_schemas import TagCreate
from knowledge_os.services.brain import Brain
from knowledge_os.services.tag_service import TagService

from .test_relations_v2 import rec, seed


def test_tag_criada_fica_no_yaml_da_raiz(conn, data_dir):
    TagService().create(["spring"])
    assert "spring" in (data_dir / ".knowledge.yaml").read_text(encoding="utf-8")
    assert TagService().list() == [{"name": "spring", "count": 0}]


def test_tag_usada_em_item_aparece_na_lista(conn):
    seed(rec("a", tags=["kafka"]))
    assert TagService().list() == [{"name": "kafka", "count": 1}]
    assert TagService().create(["kafka"])["existing"] == ["kafka"]


def test_set_on_item_poe_e_tira_tag_existente(conn):
    seed(rec("a", tags=["x"]), rec("b", tags=["y"]))
    assert [t.name for t in TagService().set_on_item("b", "x", True)] == ["x", "y"]
    assert [t.name for t in TagService().set_on_item("b", "x", False)] == ["y"]
    assert Brain().snapshot.get("a").tags == ["x"]
    with pytest.raises(NotFoundError):
        TagService().set_on_item("b", "nao-existe", True)


def test_tag_schema_length():
    with pytest.raises(PydanticValidationError):
        TagCreate(name="x" * 101)
    with pytest.raises(PydanticValidationError):
        TagCreate(name="")
