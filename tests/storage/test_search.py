"""Testes da busca em memória (storage/search.py): normalização, BM25 e índice."""

from datetime import datetime

import pytest

from knowledge_os.storage.files import FileStore, ItemRecord
from knowledge_os.storage.search import Candidate, SearchIndex, search, stem, terms


def _rec(id_: str, **over) -> ItemRecord:
    base = dict(
        id=id_, key=None, workspace="W", project="P", subject=None, type="howto",
        subtype=None, scope=None, title="Titulo", status="active", tags=[], links=[],
        scope_paths=[], ttl_days=None, keywords=None, source=None, origin="agent",
        verified_at=None, verified_commit=None, created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1), relations=[], summary="Resumo", content="Conteudo",
    )
    base.update(over)
    return ItemRecord(**base)


def _c(*records: ItemRecord) -> list[Candidate]:
    return [Candidate(r) for r in records]


def _ids(hits) -> list[str]:
    return [h.record.id for h in hits]


def test_radical_ptbr():
    assert stem("migracao") == stem("migracoes") == stem("migrar") == "migr"
    assert terms("Migrações de dados") == ["migr", "dado"]
    assert stem("cliente") == "cliente"


@pytest.mark.parametrize("q", ["migração", "migracao", "migrações", "MIGRAR"])
def test_acha_sem_acento_plural_e_verbo(q):
    alvo = _rec("a", title="Migrações com Flyway")
    outro = _rec("b", title="Deploy")
    assert _ids(search(_c(alvo, outro), q, 10)) == ["a"]


def test_prefixo():
    alvo = _rec("a", content="idempotencia garantida")
    assert _ids(search(_c(alvo), "idempot", 10)) == ["a"]
    assert _ids(search(_c(alvo), "idempotente", 10)) == ["a"]


def test_peso_do_titulo_acima_do_corpo():
    corpo = _rec("corpo", title="Outra coisa", content="kafka")
    titulo = _rec("titulo", title="Kafka", content="nada")
    res = search(_c(corpo, titulo), "kafka", 10)
    assert _ids(res) == ["titulo", "corpo"]
    assert res[0].score > res[1].score > 0


def test_keywords_entram_na_busca():
    alvo = _rec("a", title="Valores monetários", keywords="dinheiro centavos BigDecimal")
    assert _ids(search(_c(alvo, _rec("b")), "centavos", 10)) == ["a"]


def test_and_antes_de_or():
    ambos = _rec("ambos", title="Flyway kubernetes")
    um = _rec("um", title="Flyway")
    assert _ids(search(_c(ambos, um), "flyway kubernetes", 10)) == ["ambos"]
    assert _ids(search(_c(um), "flyway kubernetes", 10)) == ["um"]
    assert search(_c(um), "zzz yyy", 10) == []


def test_relevancia_vence_boost_pequeno():
    alvo = _rec("alvo", title="Cache com Redis", summary="TTL e invalidação no Redis")
    outro = _rec("outro", title="Deploy do backend", summary="pipeline",
                 content="o deploy reinicia o redis")
    res = search([Candidate(outro, boost=1.1), Candidate(alvo)], "redis cache", 10)
    assert _ids(res)[0] == "alvo"


def test_stopwords_e_termos_curtos():
    alvo = _rec("a", title="UI de cadastro")
    assert _ids(search(_c(alvo), "UI", 10)) == ["a"]
    assert _ids(search(_c(alvo), "de", 10)) == ["a"]
    assert search(_c(alvo), "!!", 10) == []


def test_sintaxe_crua_vira_texto():
    alvo = _rec("a", title="aberta")
    assert _ids(search(_c(alvo), '"aberta', 10)) == ["a"]
    assert _ids(search(_c(alvo), "aberta OR fechada", 10)) == ["a"]


def test_sem_consulta_ordena_por_updated_at_e_limita():
    recs = [_rec(str(i), updated_at=datetime(2026, 1, 1 + i)) for i in range(5)]
    res = search(_c(*recs), "", 3)
    assert _ids(res) == ["4", "3", "2"]
    assert all(h.score == 1.0 for h in res)


def test_empate_usa_updated_at():
    a = _rec("a", content="nginx", updated_at=datetime(2026, 1, 2))
    b = _rec("b", content="nginx", updated_at=datetime(2026, 1, 9))
    assert _ids(search(_c(a, b), "nginx", 10)) == ["b", "a"]


def test_so_considera_os_candidatos_passados():
    a, b = _rec("a", content="helm"), _rec("b", content="helm")
    assert _ids(search(_c(b), "helm", 10)) == ["b"]
    assert len(search(_c(a, b), "helm", 1)) == 1


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

    def found(q):
        return _ids(search(_c(*store.items()), q, 10, index=store.index))

    assert found("grafana") == ["a"]
    store.write(_rec("a", key="k/a", content="loki"))
    assert found("grafana") == []
    store.delete("b")
    assert found("prometheus") == []
    assert len(store.index) == 1
