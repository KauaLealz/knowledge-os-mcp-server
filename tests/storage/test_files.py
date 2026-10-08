"""Testes do armazenamento em arquivos (storage/files.py)."""

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from knowledge_os.storage.files import FileStore, ItemRecord


def _rec(id_: str = "id-1", **over) -> ItemRecord:
    base = dict(
        id=id_, key=f"regra/{id_}", workspace="Polara", project="App", subject=None,
        type="rule", title="Titulo", status="active", memory_class="longterm",
        tags=[], labels=[], scope_paths=[], confidence=None, importance=None, ttl_days=None,
        keywords=None, source=None, created_at=datetime(2026, 1, 1, 10, 0, 0),
        updated_at=datetime(2026, 1, 2, 10, 0, 0), relations=[], summary="Resumo",
        content="Corpo\n",
    )
    base.update(over)
    return ItemRecord(**base)


def _bump_mtime(path: Path, delta_ns: int = 2_000_000_000) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + delta_ns))


@pytest.fixture
def store(tmp_path) -> FileStore:
    return FileStore(tmp_path / "dados")


def test_write_e_leitura_ida_e_volta(store):
    rel = store.write(_rec(tags=["java"], importance=5, subject="Pagamentos"))
    assert rel == "polara/app/regra/id-1.md"
    assert (store.root / rel).is_file()
    novo = FileStore(store.root)
    got = novo.get("id-1")
    assert got is not None and got.path == rel
    assert got.title == "Titulo" and got.tags == ["java"] and got.importance == 5
    assert got.subject == "Pagamentos" and got.content == "Corpo\n"


def test_varredura_consultas(store):
    store.write(_rec("a", subject="S1"))
    store.write(_rec("b", project="Outro", subject="S2"))
    store.write(_rec("c", workspace="Pessoal", project="Geral"))
    store.refresh()
    assert {r.id for r in store.items()} == {"a", "b", "c"}
    assert store.workspaces() == ["Pessoal", "Polara"]
    assert store.projects("Polara") == ["App", "Outro"]
    assert store.subjects("Polara", "App") == ["S1"]
    assert store.by_key("Polara", "App", "regra/a").id == "a"
    assert store.by_key("polara", "App", "regra/a") is None  # nome exato
    assert store.get("zzz") is None


def test_ignora_pastas_ocultas_e_arquivo_invalido_vai_para_errors(store):
    store.write(_rec("a"))
    for oculto in (".git", ".secrets"):
        d = store.root / oculto
        d.mkdir()
        (d / "x.md").write_text("lixo", encoding="utf-8")
    ruim = store.root / "polara" / "app" / "ruim.md"
    ruim.write_text("sem frontmatter", encoding="utf-8")
    store.refresh()
    assert [r.id for r in store.items()] == ["a"]
    assert list(store.errors) == ["polara/app/ruim.md"]
    assert "frontmatter" in store.errors["polara/app/ruim.md"]


def test_refresh_incremental_so_reparseia_o_que_mudou(store, monkeypatch):
    store.write(_rec("a"))
    store.write(_rec("b"))
    store.refresh()
    import knowledge_os.storage.files as files_mod

    chamadas: list[str] = []
    original = files_mod.parse_item_file

    def espiao(raw):
        chamadas.append(raw)
        return original(raw)

    monkeypatch.setattr(files_mod, "parse_item_file", espiao)
    store.refresh()
    assert chamadas == []

    alvo = store.root / "polara/app/regra/a.md"
    alvo.write_text(alvo.read_text(encoding="utf-8").replace("Titulo", "Novo"), encoding="utf-8")
    _bump_mtime(alvo)
    store.refresh()
    assert len(chamadas) == 1
    assert store.get("a").title == "Novo"

    alvo.unlink()
    store.refresh()
    assert store.get("a") is None and store.get("b") is not None


def test_arquivo_novo_externo_aparece(store):
    store.write(_rec("a"))
    outro = FileStore(store.root)
    outro.write(_rec("b"))
    store.refresh()
    assert store.get("b") is not None


def test_mudanca_de_key_remove_arquivo_antigo(store):
    store.write(_rec("a"))
    rel = store.write(_rec("a", key="regra/novo"))
    assert rel == "polara/app/regra/novo.md"
    assert not (store.root / "polara/app/regra/a.md").exists()
    store.refresh()
    assert [r.path for r in store.items()] == [rel]
    rel2 = store.write(_rec("a", key="regra/novo", project="Outro"))
    assert not (store.root / rel).exists()
    assert rel2 == "polara/outro/regra/novo.md"


def test_id_duplicado_mais_recente_vence(store):
    store.write(_rec("a"))
    antigo = store.root / "polara/app/regra/a.md"
    copia = store.root / "polara/app/regra/copia.md"
    copia.write_text(
        antigo.read_text(encoding="utf-8").replace("Titulo", "Copia"), encoding="utf-8"
    )
    _bump_mtime(copia)
    store.refresh()
    assert store.get("a").title == "Copia"
    assert [r.id for r in store.items()] == ["a"]
    assert "polara/app/regra/a.md" in store.errors


def test_delete(store):
    rel = store.write(_rec("a"))
    assert store.delete("a") == rel
    assert not (store.root / rel).exists()
    assert store.get("a") is None
    assert store.delete("a") is None


def test_escrita_atomica_nao_deixa_temporario(store, monkeypatch):
    store.write(_rec("a"))
    alvo = store.root / "polara/app/regra/a.md"
    antes = alvo.read_text(encoding="utf-8")

    def falha(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(os, "replace", falha)
    with pytest.raises(OSError):
        store.write(replace(_rec("a"), title="Outro"))
    assert alvo.read_text(encoding="utf-8") == antes
    assert sorted(p.name for p in alvo.parent.iterdir()) == ["a.md"]


def test_write_secret_sem_valor(store):
    rel = store.write(_rec("s", type="secret", key="segredo/token"))
    assert store.get("s").type == "secret"
    assert "segredo/token" in rel


def test_raiz_inexistente_e_vazia(tmp_path):
    s = FileStore(tmp_path / "nao-existe")
    assert s.items() == [] and s.workspaces() == []
