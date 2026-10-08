"""Busca do ItemService sobre os arquivos: sem content, filtros, contadores no home, limite e
leitura do que mudou por fora. O contrato v2 completo está em test_search_service.py."""

import pytest

from knowledge_os.services.brain import Item
from knowledge_os.services.item_service import ItemService
from knowledge_os.storage import local_state

VP = ("w", "p")


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _mk(svc: ItemService, ws: str = "W", pj: str = "P", **kw) -> Item:
    base = dict(type="howto", title="t", summary="s", content="c")
    base.update(kw)
    (row,) = svc.save([base], default_location=(ws, pj))
    return svc.get(row["id"])


def _ids(out):
    return [r["id"] for r in out["results"]]


def test_search_nao_retorna_content(svc):
    _mk(svc, title="Spring", summary="beans", content="ConditionalOnProperty detalhado")
    (row,) = svc.search("ConditionalOnProperty", viewpoint=VP)["results"]
    assert "content" not in row and row["matched_in"] == ["content"]
    assert isinstance(row["score"], float)


def test_search_filtra_por_tipo_e_subtipo(svc):
    _mk(svc, type="rule", content="redis")
    k = _mk(svc, type="howto", subtype="troubleshoot", content="redis")
    assert _ids(svc.search("redis", viewpoint=VP, types=["howto"],
                           subtypes=["troubleshoot"])) == [k.id]


def test_search_filtra_por_workspace(svc):
    _mk(svc, content="helm")
    o = _mk(svc, ws="Outro", pj="X", content="helm")
    assert _ids(svc.search("helm", workspace="Outro")) == [o.id]


def test_search_filtra_por_tags_em_conjuncao(svc):
    a = _mk(svc, content="pix", tags=["pagamentos", "critico"])
    _mk(svc, content="pix", tags=["pagamentos"])
    assert _ids(svc.search("pix", viewpoint=VP, tags=["pagamentos", "critico"])) == [a.id]


def test_search_soma_shown_e_get_many_soma_opened(svc):
    it = _mk(svc, content="grafana")
    assert it.access_count == 0
    svc.search("grafana", viewpoint=VP)
    svc.get_many(ids=[it.id])
    svc.get_many(ids=[it.id])
    got = svc.get(it.id)
    assert got.access_count == 2 and got.last_accessed is not None
    assert local_state.get_usage("teste")[it.id]["shown"] == 1


def test_uso_fica_no_home_e_nao_no_arquivo(svc, data_dir, _isolated_home):
    it = _mk(svc, content="grafana")
    before = (data_dir / it.path).read_text(encoding="utf-8")
    svc.search("grafana", viewpoint=VP)
    assert (data_dir / it.path).read_text(encoding="utf-8") == before
    assert (_isolated_home / "usage" / "teste.json").is_file()


def test_search_limit(svc):
    svc.save([{"type": "howto", "title": f"n{i}", "summary": "s", "content": "nginx"}
              for i in range(5)], default_location=("W", "P"))
    assert len(svc.search("nginx", viewpoint=VP, limit=3)["results"]) == 3


def test_search_reflete_update(svc):
    it = _mk(svc, content="antigo")
    svc.update(it.id, content="novissimo")
    assert _ids(svc.search("antigo", viewpoint=VP)) == []
    assert _ids(svc.search("novissimo", viewpoint=VP)) == [it.id]


def test_search_ve_arquivo_editado_por_fora(svc, data_dir):
    it = _mk(svc, content="antigo")
    path = data_dir / it.path
    path.write_text(path.read_text(encoding="utf-8").replace("antigo", "externo"),
                    encoding="utf-8")
    assert _ids(svc.search("externo", viewpoint=VP)) == [it.id]


def test_search_query_vazia_com_filtro_lista_tudo(svc):
    _mk(svc)
    assert len(svc.search("", viewpoint=VP, types=["howto"])["results"]) == 1


def test_search_aspas_sao_texto_comum(svc):
    it = _mk(svc, title="aberta")
    assert _ids(svc.search('"aberta', viewpoint=VP)) == [it.id]
