"""Relações no frontmatter: consistência ao apagar/mover o alvo, e o schema da API.

O contrato em lote do RelationService está em test_relations_v2.py.
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from knowledge_os.schemas.relation_schemas import RelationCreate
from knowledge_os.services.brain import Brain
from knowledge_os.services.relation_service import RelationService

from .test_relations_v2 import VP, entry, rec, seed, text_of


@pytest.fixture
def ab(conn):
    seed(rec("a"), rec("b"))
    RelationService().create([entry(type_="references")], viewpoint=VP)


def test_id_da_relacao_e_estavel(ab):
    (first,) = RelationService().list("a")
    RelationService().create([entry(type_="references")], viewpoint=VP)
    (second,) = RelationService().list("a")
    assert first.id == second.id


def test_apagar_o_alvo_tira_a_relacao_da_origem(ab):
    brain = Brain()
    with brain.editing() as d:
        d.remove("b")
        brain.commit(d, "remove b")
    assert RelationService().list("a") == []
    assert "relations: []" in text_of("a")


def test_mover_o_alvo_de_project_troca_a_key_pelo_id(ab):
    brain = Brain()
    with brain.editing() as d:
        d.update("b", workspace="Outro", project="longe")
        brain.commit(d, "move b")
    (rel,) = RelationService().list("a")
    assert rel.target_item_id == "b"
    assert "target: b" in text_of("a")


def test_schema_validates_type():
    with pytest.raises(PydanticValidationError):
        RelationCreate(source_item_id="a", target_item_id="b", relation_type="bad")
