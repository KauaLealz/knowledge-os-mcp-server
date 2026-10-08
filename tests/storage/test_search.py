"""Testes da busca em memória (storage/search.py)."""

from datetime import datetime

import pytest

from knowledge_os.storage.files import FileStore, ItemRecord
from knowledge_os.storage.search import SearchIndex, search, stem, terms


def _rec(id_: str, **over) -> ItemRecord:
    base = dict(
        id=id_, key=None, workspace="W", project="P", subject=None, type="knowledge",
        title="Titulo", status="active", memory_class="longterm", tags=[], labels=[],
        scope_paths=[], confidence=None, importance=None, ttl_days=None, keywords=None,
        source=None, created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        relations=[], summary="Resumo", content="Conteudo",
    )
    base.update(over)
    return ItemRecord(**base)


def _ids(res) -> list[str]:
    return [r.id for r, _ in res]


def test_radical_ptbr():
    assert stem("migracao") == stem("migracoes") == stem("migrar") == "migr"
    assert terms("Migrações de dados") == ["migr", "dado"]
    assert stem("cliente") == "cliente"


@pytest.mark.parametrize("q", ["migração", "migracao", "migrações", "MIGRAR"])
def test_acha_sem_acento_plural_e_verbo(q):
    alvo = _rec("a", title="Migrações com Flyway")
    outro = _rec("b", title="Deploy")
    assert _ids(search([alvo, outro], q, 10)) == ["a"]


def test_prefixo():
    alvo = _rec("a", content="idempotencia garantida")
    assert _ids(search([alvo], "idempot", 10)) == ["a"]
    assert _ids(search([alvo], "idempotente", 10)) == ["a"]


def test_peso_do_titulo_acima_do_corpo():
    corpo = _rec("corpo", title="Outra coisa", content="kafka")
    titulo = _rec("titulo", title="Kafka", content="nada")
    res = search([corpo, titulo], "kafka", 10)
    assert _ids(res) == ["titulo", "corpo"]
    assert res[0][1] > res[1][1] > 0


def test_keywords_entram_na_busca():
    alvo = _rec("a", title="Valores monetários", keywords="dinheiro centavos BigDecimal")
    assert _ids(search([alvo, _rec("b")], "centavos", 10)) == ["a"]


def test_and_antes_de_or():
    ambos = _rec("ambos", title="Flyway kubernetes")
    um = _rec("um", title="Flyway")
    assert _ids(search([ambos, um], "flyway kubernetes", 10)) == ["ambos"]
    assert _ids(search([um], "flyway kubernetes", 10)) == ["um"]
    assert search([um], "zzz yyy", 10) == []


def test_relevancia_vence_desempate():
    alvo = _rec("alvo", title="Cache com Redis", summary="TTL e invalidação no Redis",
                importance=1)
    outro = _rec("outro", title="Deploy do backend", summary="pipeline",
                 content="o deploy reinicia o redis", importance=10)
    res = search([outro, alvo], "redis cache", 10, key=lambda r: r.importance or 0)
    assert _ids(res)[0] == "alvo"


def test_stopwords_e_termos_curtos():
    alvo = _rec("a", title="UI de cadastro")
    assert _ids(search([alvo], "UI", 10)) == ["a"]
    assert _ids(search([alvo], "de", 10)) == ["a"]
    assert search([alvo], "!!", 10) == []


def test_sintaxe_crua_vira_texto():
    alvo = _rec("a", title="aberta")
    assert _ids(search([alvo], '"aberta', 10)) == ["a"]
    assert _ids(search([alvo], "aberta OR fechada", 10)) == ["a"]


def test_sem_consulta_ordena_pelo_desempate_e_limita():
    recs = [_rec(str(i), importance=i) for i in range(5)]
    res = search(recs, "", 3, key=lambda r: r.importance)
    assert _ids(res) == ["4", "3", "2"]
    assert all(score == 0.0 for _, score in res)


def test_empate_usa_key():
    a = _rec("a", content="nginx", importance=2)
    b = _rec("b", content="nginx", importance=9)
    assert _ids(search([a, b], "nginx", 10, key=lambda r: r.importance)) == ["b", "a"]


def test_so_considera_os_records_passados():
    a, b = _rec("a", content="helm"), _rec("b", content="helm")
    assert _ids(search([b], "helm", 10)) == ["b"]
    assert len(search([a, b], "helm", 1)) == 1


def test_indice_incremental():
    idx = SearchIndex()
    idx.add(_rec("a", content="antigo"))
    assert idx.docs_for("antig")
    idx.add(_rec("a", content="novissimo"))
    assert not idx.docs_for("antig")
    idx.remove("a")
    assert len(idx) == 0


def test_filestore_mantem_indice(tmp_path):
    store = FileStore(tmp_path)
    store.write(_rec("a", key="k/a", content="grafana"))
    store.write(_rec("b", key="k/b", content="prometheus"))
    res = search(store.items(), "grafana", 10, index=store.index)
    assert _ids(res) == ["a"]
    store.write(_rec("a", key="k/a", content="loki"))
    assert search(store.items(), "grafana", 10, index=store.index) == []
    store.delete("b")
    assert search(store.items(), "prometheus", 10, index=store.index) == []
    assert len(store.index) == 1
