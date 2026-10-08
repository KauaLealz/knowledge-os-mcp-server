"""Testes de TagService e LabelService (etiquetas nos itens e no `.knowledge.yaml` da raiz)."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.schemas.label_schemas import LabelCreate
from knowledge_os.schemas.tag_schemas import TagCreate
from knowledge_os.services.brain import DEFAULT_LABELS
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.label_service import LabelService
from knowledge_os.services.tag_service import TagService


def test_tag_create_list_unique(conn, data_dir):
    svc = TagService()
    tag = svc.create("spring")
    assert tag.id == "spring"
    assert [t.name for t in svc.list()] == ["spring"]
    assert "spring" in (data_dir / ".knowledge.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        svc.create("spring")


def test_tag_usada_em_item_aparece_na_lista(sample_workspace, sample_project):
    ItemService().create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                         type="rule", memory_class="longterm", title="T", summary="s",
                         content="c", tags=["kafka"])
    assert [t.name for t in TagService().list()] == ["kafka"]
    with pytest.raises(ValidationError):
        TagService().create("kafka")


def test_tag_empty_name_rejected(conn):
    with pytest.raises(ValidationError):
        TagService().create("   ")


def test_tag_delete_removes_from_items(sample_workspace, sample_project):
    it = ItemService().create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                              type="rule", memory_class="longterm", title="T", summary="s",
                              content="c", tags=["x", "y"])
    assert TagService().delete("x") is True
    assert ItemService().get(it.id).tags == ["y"]
    with pytest.raises(NotFoundError):
        TagService().delete("x")


def test_tag_schema_length():
    with pytest.raises(PydanticValidationError):
        TagCreate(name="x" * 101)
    with pytest.raises(PydanticValidationError):
        TagCreate(name="")


def test_labels_padrao_existem_sem_nada_gravado(conn):
    assert [lb.name for lb in LabelService().list()] == sorted(DEFAULT_LABELS)


def test_label_create_list_unique(conn):
    svc = LabelService()
    label = svc.create("gold")
    assert label.id == "gold"
    assert "gold" in [x.name for x in svc.list()]
    with pytest.raises(ValidationError):
        svc.create("gold")
    with pytest.raises(ValidationError):
        svc.create("official")  # padrão já existe


def test_label_delete_removes_from_items_e_padrao_some(sample_workspace, sample_project):
    it = ItemService().create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                              type="rule", memory_class="longterm", title="T", summary="s",
                              content="c", labels=["official", "critical"])
    assert LabelService().delete("official") is True
    assert ItemService().get(it.id).labels == ["critical"]
    assert "official" not in [lb.name for lb in LabelService().list()]
    LabelService().create("official")
    assert "official" in [lb.name for lb in LabelService().list()]


def test_label_delete_inexistente(conn):
    with pytest.raises(NotFoundError):
        LabelService().delete("nope")


def test_label_schema_length():
    with pytest.raises(PydanticValidationError):
        LabelCreate(name="x" * 101)
    with pytest.raises(PydanticValidationError):
        LabelCreate(name="")
