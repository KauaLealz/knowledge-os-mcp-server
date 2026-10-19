"""RelationService v6: relações item→item (links), em lote atômico, resolvidas por key/id na
conexão (sem scope, sem supersedes)."""

import subprocess
from datetime import datetime

import pytest

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import LINK_RELATIONS
from knowledge_os.services.brain import Brain
from knowledge_os.services.relation_service import RelationService
from knowledge_os.storage.files import ItemRecord

VP = ("w", "p")  # repositório ligado a W/P (viewpoint é ignorado no v6)


def rec(id_: str, workspace: str = "W", project: str | None = "P", **over) -> ItemRecord:
    base = dict(
        id=id_, key=f"rule/{id_}", workspace=workspace, project=project, subject=None,
        type="rule", title=f"Item {id_}", tags=[], links=[],
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        summary="Resumo", content="",
    )
    base.update(over)
    return ItemRecord(**base)


def seed(*records: ItemRecord, metas: dict | None = None) -> Brain:
    """Grava os itens (e `.knowledge.yaml`) direto pelo Brain, sem passar pelo ItemService."""
    brain = Brain()
    with brain.editing() as d:
        for r in records:
            d.put(r)
        for rel, data in (metas or {}).items():
            d.set_meta(rel, data)
        brain.commit(d, "seed")
    return brain


def text_of(item_id: str) -> str:
    brain = Brain()
    return (brain.root / brain.snapshot.get(item_id).path).read_text(encoding="utf-8")


def pairs():
    return sorted((r.source_item_id, r.relation_type, r.target_item_id)
                  for r in Brain().snapshot.relations())


def commits(folder) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=folder,
                         capture_output=True, text=True, check=True)
    return int(out.stdout)


@pytest.fixture
def abc(conn):
    return seed(rec("a"), rec("b"), rec("c"))


def entry(source="rule/a", type_="depends_on", target="rule/b"):
    return {"source": source, "type": type_, "target": target}


def test_cria_em_lote_e_devolve_uma_linha_por_entrada(abc):
    rows = RelationService().create(
        [entry(), entry("rule/a", "relates_to", "rule/c")], viewpoint=VP)
    assert [(r["index"], r["type"], r["action"]) for r in rows] == [
        (0, "depends_on", "created"), (1, "relates_to", "created")]
    assert rows[0]["source"] == "rule/a" and rows[0]["target"] == "rule/b"
    assert pairs() == [("a", "depends_on", "b"), ("a", "relates_to", "c")]


def test_frontmatter_da_origem_reflete_a_relacao(abc):
    RelationService().create([entry()], viewpoint=VP)
    text = text_of("a")
    assert "rel: depends_on" in text and "item: rule/b" in text
    assert "links: []" in text_of("b")


def test_duplicata_e_unchanged_e_nao_gera_commit(abc, data_dir):
    RelationService().create([entry()], viewpoint=VP)
    before = commits(data_dir)
    rows = RelationService().create([entry(), entry()], viewpoint=VP)
    assert [r["action"] for r in rows] == ["unchanged", "unchanged"]
    assert commits(data_dir) == before
    assert len(pairs()) == 1


def test_duplicata_dentro_do_mesmo_lote(abc):
    rows = RelationService().create([entry(), entry()], viewpoint=VP)
    assert [r["action"] for r in rows] == ["created", "unchanged"]


def test_lote_e_um_commit_so(abc, data_dir):
    before = commits(data_dir)
    RelationService().create([entry(), entry("rule/b", "relates_to", "rule/c")], viewpoint=VP)
    assert commits(data_dir) == before + 1


def test_tipo_invalido_lista_os_validos_e_nao_grava_nada(abc):
    with pytest.raises(ValidationError) as exc:
        RelationService().create([entry(), entry(type_="likes")], viewpoint=VP)
    message = str(exc.value)
    assert "items[1]" in message and all(t in message for t in LINK_RELATIONS)
    assert pairs() == []


def test_vinte_e_uma_entradas_e_erro(abc):
    with pytest.raises(ValidationError, match="no máximo 20"):
        RelationService().create([entry()] * 21, viewpoint=VP)
    assert RelationService().create([entry()] * 20, viewpoint=VP)[0]["action"] == "created"


def test_atomico_um_erro_desfaz_o_lote(abc):
    with pytest.raises(NotFoundError, match=r"items\[1\]"):
        RelationService().create([entry(), entry(target="rule/nao-existe")], viewpoint=VP)
    assert pairs() == []


def test_resolve_por_key_e_por_id(abc):
    rows = RelationService().create(
        [entry("a", "relates_to", "rule/b"), entry("rule/a", "depends_on", "c")], viewpoint=VP)
    assert [r["action"] for r in rows] == ["created", "created"]
    assert pairs() == [("a", "depends_on", "c"), ("a", "relates_to", "b")]


def test_alvo_em_outro_project_resolve_na_conexao(conn):
    # Sem scope: a resolução é por key/id na conexão inteira; o alvo noutro project resolve.
    seed(rec("a"), rec("far", "W", "Q"))
    RelationService().create([entry(target="rule/far")], viewpoint=VP)
    assert pairs() == [("a", "depends_on", "far")]
    assert "item: far" in text_of("a")  # projects diferentes: vai pelo id


def test_item_inexistente_e_recusado_dizendo_como_corrigir(conn):
    seed(rec("a"))
    with pytest.raises(NotFoundError) as exc:
        RelationService().create([entry(target="rule/hidden")], viewpoint=VP)
    message = str(exc.value)
    assert "rule/hidden" in message and "conexão" in message and "id" in message
    assert pairs() == []


def test_auto_relacao_recusada(abc):
    with pytest.raises(ValidationError, match="consigo mesmo"):
        RelationService().create([entry(target="rule/a")], viewpoint=VP)


def test_entrada_malformada_diz_o_formato(abc):
    with pytest.raises(ValidationError, match="source"):
        RelationService().create([{"source": "rule/a"}], viewpoint=VP)
    with pytest.raises(ValidationError):
        RelationService().create([], viewpoint=VP)


def test_delete_em_lote_deleted_e_missing(abc):
    RelationService().create([entry()], viewpoint=VP)
    rows = RelationService().delete(
        [entry(), entry("rule/a", "relates_to", "rule/c"), entry(target="rule/zzz")],
        viewpoint=VP)
    assert [r["action"] for r in rows] == ["deleted", "missing", "missing"]
    assert pairs() == []
    assert "links: []" in text_of("a")


def test_delete_tipo_invalido(abc):
    with pytest.raises(ValidationError, match="Válidos"):
        RelationService().delete([entry(type_="x")], viewpoint=VP)


def test_list_continua_para_a_api(abc):
    RelationService().create([entry()], viewpoint=VP)
    svc = RelationService()
    assert len(svc.list("a")) == len(svc.list("b")) == 1
    assert svc.list("c") == []
    assert len(svc.list_all(relation_type="depends_on")) == 1
    assert len(svc.list_for_items(["a", "b"])) == 1 and svc.list_for_items(["a", "c"]) == []
