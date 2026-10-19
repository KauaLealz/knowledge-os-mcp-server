"""GraphService v6: vizinhança por hop, limite, filtros e sinal de uso. Relações são links
item→item (depends_on/relates_to); grafo é da conexão inteira."""

from datetime import datetime

import pytest

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.brain import Brain
from knowledge_os.services.graph import GraphService

from .test_relations_v2 import VP, rec, seed


def link(type_, target):
    return {"item": target, "rel": type_}


@pytest.fixture
def grafo(conn):
    """A -> B -> C; A aponta também para x1..x29 (30 vizinhos diretos)."""
    xs = [rec(f"x{i}", title=f"X {i}") for i in range(1, 30)]
    seed(
        rec("a", links=[link("depends_on", "howto/b"),
                        *(link("relates_to", f"rule/{x.id}") for x in xs)]),
        rec("b", links=[link("relates_to", "rule/c")], type="howto", key="howto/b"),
        rec("c"),
        *xs,
    )


def graph(keys=("rule/a",), **kw):
    return GraphService().graph(list(keys), viewpoint=VP, **kw)


def keys_of(out, hop=None):
    return {n["key"] for n in out["nodes"] if hop is None or n["hop"] == hop}


def test_limit_corta_vizinhos_e_informa_o_total_real(grafo):
    out = graph(depth=1, limit=10)
    assert len(out["nodes"]) == 11 and keys_of(out, 0) == {"rule/a"}
    assert sum(n["hop"] == 1 for n in out["nodes"]) == 10
    assert out["truncated"] is True
    assert out["total_by_hop"] == {"1": 30}


def test_sem_corte_nao_marca_truncated(grafo):
    out = graph(depth=1, limit=100)
    assert out["truncated"] is False and len(out["nodes"]) == 31


def test_depth_2_inclui_c(grafo):
    assert "rule/c" not in keys_of(graph(depth=1, limit=100))
    out = graph(depth=2, limit=100)
    assert "rule/c" in keys_of(out, 2)
    assert out["total_by_hop"] == {"1": 30, "2": 1}
    assert {"from": "howto/b", "type": "relates_to", "to": "rule/c"} in out["edges"]


def test_filtra_arestas_por_relation_types(grafo):
    out = graph(keys=("howto/b",), depth=1, relation_types=["relates_to"])
    assert out["edges"] == [{"from": "howto/b", "type": "relates_to", "to": "rule/c"}]
    assert keys_of(out) == {"howto/b", "rule/c"}
    # a toca b por depends_on, não por relates_to
    out = graph(keys=("rule/a",), depth=1, relation_types=["depends_on"])
    assert {"from": "rule/a", "type": "depends_on", "to": "howto/b"} in out["edges"]


def test_direction_out_e_in(grafo):
    out = graph(keys=("howto/b",), direction="out")
    assert keys_of(out) == {"howto/b", "rule/c"}
    out = graph(keys=("howto/b",), direction="in")
    assert keys_of(out) == {"howto/b", "rule/a"}
    assert out["edges"] == [{"from": "rule/a", "type": "depends_on", "to": "howto/b"}]
    assert keys_of(graph(direction="in", limit=100)) == {"rule/a"}


def test_types_filtra_os_nos(grafo):
    out = graph(depth=2, limit=100, types=["howto"])
    assert keys_of(out) == {"rule/a", "howto/b"}
    assert out["edges"] == [{"from": "rule/a", "type": "depends_on", "to": "howto/b"}]


def test_formato_do_no(grafo):
    out = graph(keys=("howto/b",), direction="out")
    (b,) = [n for n in out["nodes"] if n["hop"] == 0]
    assert set(b) == {"key", "id", "type", "title", "summary", "hop"}
    assert (b["id"], b["type"]) == ("b", "howto")


def test_resolve_por_id_e_varias_keys(grafo):
    out = graph(keys=("b", "rule/x1"), depth=1, direction="in")
    assert keys_of(out, 0) == {"howto/b", "rule/x1"}
    assert keys_of(out, 1) == {"rule/a"}


def test_key_inexistente_e_erro_claro(grafo):
    with pytest.raises(NotFoundError, match="rule/nao-existe"):
        graph(keys=("rule/a", "rule/nao-existe"))


def test_limites_de_entrada(grafo):
    with pytest.raises(ValidationError, match="100"):
        graph(limit=101)
    with pytest.raises(ValidationError, match="depth"):
        graph(depth=4)
    with pytest.raises(ValidationError, match="no máximo 5"):
        graph(keys=("rule/a",) * 6)
    with pytest.raises(ValidationError, match="direction"):
        graph(direction="up")
    with pytest.raises(ValidationError, match="Válidos"):
        graph(relation_types=["gosta"])
    with pytest.raises(ValidationError):
        graph(keys=())


def test_ordena_por_sinal_de_uso_depois_updated_at(grafo):
    Brain().track(["x7", "x3"])
    Brain().track(["x7"])
    out = graph(limit=2, direction="out")
    assert [n["key"] for n in out["nodes"] if n["hop"] == 1] == ["rule/x7", "rule/x3"]


def test_desempate_por_updated_at_mais_recente(conn):
    seed(
        rec("a", links=[link("relates_to", "rule/velho"), link("relates_to", "rule/novo")]),
        rec("velho", updated_at=datetime(2026, 1, 1)),
        rec("novo", updated_at=datetime(2026, 6, 1)),
    )
    out = graph(limit=1)
    assert [n["key"] for n in out["nodes"] if n["hop"] == 1] == ["rule/novo"]


def _opened(item_id):
    use = Brain().usage().get(item_id) or {}
    return use.get("opened", use.get("uses", 0))


def test_nos_devolvidos_contam_como_abertos_exceto_os_de_entrada(grafo):
    graph(keys=("howto/b",), direction="out")
    assert _opened("c") == 1 and _opened("b") == 0


def test_itens_linkados_aparecem_no_grafo(conn):
    seed(
        rec("a", links=[link("relates_to", "rule/b")]),
        rec("b"),
    )
    assert {"rule/a", "rule/b"} <= keys_of(graph())
