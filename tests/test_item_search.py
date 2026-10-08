"""Testes da busca textual do ItemService (em memória, sobre os arquivos)."""

import pytest

from knowledge_os.services.brain import Item, Project, Workspace
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.project_service import ProjectService


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _mk(svc: ItemService, ws: Workspace, dm: Project, **kw) -> Item:
    base = dict(
        workspace_id=ws.id, project_id=dm.id, type="knowledge", memory_class="longterm",
        title="t", summary="s", content="c",
    )
    base.update(kw)
    return svc.create(**base)


def test_search_nao_retorna_content(svc, sample_workspace, sample_project):
    _mk(svc, sample_workspace, sample_project, title="Spring", summary="beans",
        content="ConditionalOnProperty detalhado")
    res = svc.search(sample_workspace.id, None, "ConditionalOnProperty")
    assert len(res) == 1
    assert set(res[0]) == {
        "id", "key", "type", "memory_class", "project", "subject", "title", "summary", "score",
        "uses", "tags", "labels", "workspace_id", "project_id"}
    assert "content" not in res[0]
    assert isinstance(res[0]["score"], float)


def test_search_ordena_por_importance_desc(svc, sample_workspace, sample_project):
    a = _mk(svc, sample_workspace, sample_project, title="a", content="kafka", importance=2)
    b = _mk(svc, sample_workspace, sample_project, title="b", content="kafka", importance=9)
    res = svc.search(sample_workspace.id, None, "kafka")
    assert [r["id"] for r in res] == [b.id, a.id]


def test_search_filtros_types_e_memory_classes(svc, sample_workspace, sample_project):
    _mk(svc, sample_workspace, sample_project, type="rule", content="redis")
    k = _mk(svc, sample_workspace, sample_project, type="knowledge",
            memory_class="canonical", content="redis")
    res = svc.search(sample_workspace.id, None, "redis", types=["knowledge"],
                     memory_classes=["canonical"])
    assert [r["id"] for r in res] == [k.id]


def test_search_filtra_por_project_e_workspace(svc, sample_workspace, sample_project):
    other = ProjectService().create(sample_workspace.id, "Other")
    _mk(svc, sample_workspace, sample_project, content="helm")
    o = _mk(svc, sample_workspace, other, content="helm")
    res = svc.search(sample_workspace.id, other.id, "helm")
    assert [r["id"] for r in res] == [o.id]
    assert svc.search("ws_inexistente", None, "helm") == []


def test_search_filtra_por_tags_e_labels_em_conjuncao(svc, sample_workspace, sample_project):
    a = _mk(svc, sample_workspace, sample_project, content="pix", tags=["pagamentos"],
            labels=["critical"])
    _mk(svc, sample_workspace, sample_project, content="pix", tags=["pagamentos"])
    res = svc.search(sample_workspace.id, None, "pix", tags=["pagamentos"], labels=["critical"])
    assert [r["id"] for r in res] == [a.id]
    assert res[0]["tags"] == ["pagamentos"] and res[0]["labels"] == ["critical"]


def test_search_conta_uso(svc, sample_workspace, sample_project):
    it = _mk(svc, sample_workspace, sample_project, content="grafana")
    assert it.access_count == 0
    svc.search(sample_workspace.id, None, "grafana")
    svc.search(sample_workspace.id, None, "grafana")
    got = svc.get(it.id)
    assert got.access_count == 2
    assert got.last_accessed is not None


def test_uso_fica_no_home_e_nao_no_arquivo(svc, sample_workspace, sample_project, data_dir,
                                           _isolated_home):
    it = _mk(svc, sample_workspace, sample_project, content="grafana")
    before = (data_dir / it.path).read_text(encoding="utf-8")
    svc.search(sample_workspace.id, None, "grafana")
    assert (data_dir / it.path).read_text(encoding="utf-8") == before
    assert (_isolated_home / "usage" / "teste.json").is_file()


def test_search_limit(svc, sample_workspace, sample_project):
    svc.save([{"workspace": sample_workspace.id, "project": sample_project.id,
               "type": "knowledge", "title": f"n{i}", "summary": "s", "content": "nginx"}
              for i in range(5)])
    assert len(svc.search(sample_workspace.id, None, "nginx", limit=3)) == 3


def test_search_reflete_update(svc, sample_workspace, sample_project):
    it = _mk(svc, sample_workspace, sample_project, content="antigo")
    svc.update(it.id, content="novissimo")
    assert svc.search(sample_workspace.id, None, "antigo") == []
    assert len(svc.search(sample_workspace.id, None, "novissimo")) == 1


def test_search_ve_arquivo_editado_por_fora(svc, sample_workspace, sample_project, data_dir):
    it = _mk(svc, sample_workspace, sample_project, content="antigo")
    path = data_dir / it.path
    path.write_text(path.read_text(encoding="utf-8").replace("antigo", "externo"),
                    encoding="utf-8")
    assert [r["id"] for r in svc.search(sample_workspace.id, None, "externo")] == [it.id]


def test_search_query_vazia_lista_tudo(svc, sample_workspace, sample_project):
    _mk(svc, sample_workspace, sample_project)
    assert len(svc.search(sample_workspace.id, None, "")) == 1


def test_search_aspas_sao_texto_comum(svc, sample_workspace, sample_project):
    it = _mk(svc, sample_workspace, sample_project, title="aberta")
    assert [r["id"] for r in svc.search(sample_workspace.id, None, '"aberta')] == [it.id]
