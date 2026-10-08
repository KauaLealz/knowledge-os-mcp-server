"""TagService v2: vocabulário gerenciado, contagem, renomear/mesclar, remover e ensure_in_draft."""

import subprocess

import pytest
import yaml

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.brain import META_FILE, Brain
from knowledge_os.services.tag_service import TagService

from .test_relations_v2 import rec, seed


def vocabulary(data_dir) -> list[str]:
    path = data_dir / META_FILE
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("tags") or []


def git_subjects(folder) -> list[str]:
    out = subprocess.run(["git", "log", "--format=%s"], cwd=folder, capture_output=True,
                         text=True, check=True)
    return out.stdout.splitlines()


def tags_of(item_id: str) -> list[str]:
    return list(Brain().snapshot.get(item_id).tags)


@pytest.fixture
def itens(conn):
    seed(rec("a", tags=["pix", "java"]), rec("b", tags=["pix"]), rec("c", tags=["kafka"]))


def test_list_traz_contagem_e_count_zero_do_vocabulario(itens):
    TagService().create(["vazia"])
    assert TagService().list() == [
        {"name": "java", "count": 1}, {"name": "kafka", "count": 1},
        {"name": "pix", "count": 2}, {"name": "vazia", "count": 0},
    ]


def test_create_separa_criadas_e_existentes_e_normaliza(itens, data_dir):
    out = TagService().create(["Pagamentos Pix", "pix", "pagamentos-pix"])
    assert out == {"created": ["pagamentos-pix"], "existing": ["pix"]}
    assert vocabulary(data_dir) == ["pagamentos-pix"]
    assert TagService().create(["pix"]) == {"created": [], "existing": ["pix"]}


def test_create_nome_invalido_e_lista_vazia(conn):
    with pytest.raises(ValidationError):
        TagService().create(["   "])
    with pytest.raises(ValidationError):
        TagService().create([])


def test_update_renomeia_nos_itens_e_no_vocabulario_num_commit(itens, data_dir):
    TagService().create(["pix"])
    before = len(git_subjects(data_dir))
    assert TagService().update("pix", "pagamentos-pix") == {"renamed": 2, "merged": False}
    assert len(git_subjects(data_dir)) == before + 1
    assert tags_of("a") == ["pagamentos-pix", "java"] and tags_of("b") == ["pagamentos-pix"]
    assert vocabulary(data_dir) == ["pagamentos-pix"]
    assert "pix" not in [t["name"] for t in TagService().list()]


def test_update_para_nome_existente_mescla_sem_duplicar(itens):
    seed(rec("d", tags=["pix", "java"]))
    out = TagService().update("pix", "java")
    assert out == {"renamed": 3, "merged": True}
    assert tags_of("a") == ["java"] and tags_of("b") == ["java"] and tags_of("d") == ["java"]
    assert {t["name"]: t["count"] for t in TagService().list()} == {"java": 3, "kafka": 1}


def test_update_tag_inexistente_lista_as_existentes(itens):
    with pytest.raises(NotFoundError, match="kafka"):
        TagService().update("nao-existe", "x")


def test_update_normaliza_o_novo_nome(itens):
    TagService().update("kafka", "Mensageria Kafka")
    assert tags_of("c") == ["mensageria-kafka"]


def test_delete_sem_confirm_e_previa(itens):
    out = TagService().delete(["pix", "kafka"])
    assert out == {"status": "preview", "tags": [{"name": "pix", "items": 2},
                                                  {"name": "kafka", "items": 1}]}
    assert tags_of("a") == ["pix", "java"]


def test_delete_com_confirm_remove_dos_itens_e_do_vocabulario(itens, data_dir):
    TagService().create(["pix"])
    before = len(git_subjects(data_dir))
    out = TagService().delete(["pix"], confirm=True)
    assert out["status"] == "deleted" and out["tags"] == [{"name": "pix", "items": 2}]
    assert tags_of("a") == ["java"] and tags_of("b") == []
    assert vocabulary(data_dir) == []
    assert len(git_subjects(data_dir)) == before + 1
    assert "pix" not in [t["name"] for t in TagService().list()]


def test_delete_tag_inexistente(itens):
    with pytest.raises(NotFoundError, match="nada"):
        TagService().delete(["pix", "nada"], confirm=True)
    assert tags_of("b") == ["pix"]


def test_ensure_in_draft_cria_tag_nova_e_avisa(itens, data_dir):
    brain = Brain()
    with brain.editing() as d:
        warnings = TagService.ensure_in_draft(d, ["pix", "Brand New"])
        assert warnings == ["tag nova 'brand-new' criada"]
        brain.commit(d, "t")
    assert vocabulary(data_dir) == ["brand-new"]


def test_ensure_in_draft_avisa_com_parecida(itens):
    brain = Brain()
    with brain.editing() as d:
        warnings = TagService.ensure_in_draft(d, ["pagamento"])
        assert warnings == ["tag nova 'pagamento' criada"]  # nada parecido ainda
        warnings = TagService.ensure_in_draft(d, ["pagamentos"])
        assert warnings == ["tag nova 'pagamentos' criada; existe parecida: 'pagamento'"]
        assert TagService.ensure_in_draft(d, ["kafka", "pagamento"]) == []


def test_ensure_in_draft_conta_como_nova_a_tag_que_o_item_em_edicao_acabou_de_citar(itens):
    brain = Brain()
    with brain.editing() as d:
        d.update("a", tags=["pix", "outra-nova"])
        assert TagService.ensure_in_draft(d, ["outra-nova"]) == ["tag nova 'outra-nova' criada"]


def test_ensure_in_draft_nome_invalido(itens):
    with pytest.raises(ValidationError):
        with Brain().editing() as d:
            TagService.ensure_in_draft(d, ["!!!"])
