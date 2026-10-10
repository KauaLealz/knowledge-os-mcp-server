"""RelationService v2: relações em lote, atômicas, resolvidas pela cadeia de alcance."""

import subprocess
from datetime import datetime

import pytest

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import RELATION_TYPES
from knowledge_os.services.brain import META_FILE, Brain
from knowledge_os.services.relation_service import RelationService
from knowledge_os.storage.files import ItemRecord

VP = ("w", "p")  # repositório ligado a W/P


def rec(id_: str, workspace: str = "W", project: str = "P", **over) -> ItemRecord:
    base = dict(
        id=id_, key=f"rule/{id_}", workspace=workspace, project=project, subject=None,
        type="rule", subtype=None, scope=None, title=f"Item {id_}", status="active", tags=[],
        links=[], scope_paths=[], ttl_days=None, keywords=None, source=None, origin="agent",
        verified_at=None, verified_commit=None, created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1), relations=[], summary="Resumo", content="",
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
        [entry(), entry("rule/a", "references", "rule/c")], viewpoint=VP)
    assert [(r["index"], r["type"], r["action"]) for r in rows] == [
        (0, "depends_on", "created"), (1, "references", "created")]
    assert rows[0]["source"] == "rule/a" and rows[0]["target"] == "rule/b"
    assert pairs() == [("a", "depends_on", "b"), ("a", "references", "c")]


def test_frontmatter_da_origem_reflete_a_relacao(abc):
    RelationService().create([entry()], viewpoint=VP)
    text = text_of("a")
    assert "type: depends_on" in text and "target: rule/b" in text
    assert "relations: []" in text_of("b")


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
    RelationService().create([entry(), entry("rule/b", "related_to", "rule/c")], viewpoint=VP)
    assert commits(data_dir) == before + 1


def test_tipo_invalido_lista_os_validos_e_nao_grava_nada(abc):
    with pytest.raises(ValidationError) as exc:
        RelationService().create([entry(), entry(type_="likes")], viewpoint=VP)
    message = str(exc.value)
    assert "items[1]" in message and all(t in message for t in RELATION_TYPES)
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
        [entry("a", "related_to", "rule/b"), entry("rule/a", "references", "c")], viewpoint=VP)
    assert [r["action"] for r in rows] == ["created", "created"]
    assert pairs() == [("a", "references", "c"), ("a", "related_to", "b")]


def test_key_do_project_do_repo_vence_a_de_fora(conn):
    seed(rec("a"), rec("b"), rec("x1", "W", "Q", key="rule/b", scope="workspace"))
    RelationService().create([entry()], viewpoint=VP)
    assert pairs() == [("a", "depends_on", "b")]


def test_key_de_outro_project_com_scope_workspace_resolve(conn):
    seed(rec("a"), rec("far", "W", "Q", scope="workspace"))
    RelationService().create([entry(target="rule/far")], viewpoint=VP)
    assert pairs() == [("a", "depends_on", "far")]
    # origem e alvo em projects diferentes: o alvo vai pelo id
    assert "target: far" in text_of("a")


def test_item_fora_do_alcance_e_recusado_dizendo_como_corrigir(conn):
    seed(rec("a"), rec("hidden", "W", "Q"))  # scoped em outro project
    with pytest.raises(NotFoundError) as exc:
        RelationService().create([entry(target="rule/hidden")], viewpoint=VP)
    message = str(exc.value)
    assert "rule/hidden" in message and "alcance" in message and "scope" in message
    assert "id" in message
    assert pairs() == []


def test_global_de_outro_workspace_resolve(conn):
    seed(rec("a"), rec("g", "Outro", "X", scope="global"))
    RelationService().create([entry(target="rule/g")], viewpoint=VP)
    assert pairs() == [("a", "depends_on", "g")]


def test_supersedes_arquiva_o_alvo_na_mesma_publicacao(abc, data_dir):
    before = commits(data_dir)
    RelationService().create([entry(type_="supersedes")], viewpoint=VP)
    assert commits(data_dir) == before + 1
    fresh = Brain().snapshot
    assert fresh.get("b").status == "archived" and fresh.get("a").status == "active"
    assert fresh.get("b").updated_at > datetime(2026, 1, 1)


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
        [entry(), entry("rule/a", "references", "rule/c"), entry(target="rule/zzz")],
        viewpoint=VP)
    assert [r["action"] for r in rows] == ["deleted", "missing", "missing"]
    assert pairs() == []
    assert "relations: []" in text_of("a")


def test_delete_nao_reativa_o_alvo_arquivado(abc):
    RelationService().create([entry(type_="supersedes")], viewpoint=VP)
    RelationService().delete([entry(type_="supersedes")], viewpoint=VP)
    assert Brain().snapshot.get("b").status == "archived"


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


def test_com_yaml_de_workspace_global(conn):
    seed(rec("a"), rec("b"), metas={f"w/{META_FILE}": {"name": "W", "scope": "global"}})
    assert RelationService().create([entry()], viewpoint=VP)[0]["action"] == "created"
