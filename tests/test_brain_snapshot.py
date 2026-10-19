"""Snapshot v6: descoberta de workspace/project/subject pela árvore, tags do vocabulário + dos
itens, item em qualquer nível, e a visão do item (services/brain.py). Sem scope/ttl/subtype."""

from datetime import datetime

from knowledge_os.services import brain as brain_mod
from knowledge_os.services.brain import META_FILE, Brain, Snapshot
from knowledge_os.storage.files import FileStore, ItemRecord


def _rec(id_: str = "a", workspace: str = "W", project: str | None = "Q", **over) -> ItemRecord:
    base = dict(
        id=id_, key=f"rule/{id_}", workspace=workspace, project=project, subject=None,
        type="rule", title="Titulo", tags=[], links=[],
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        summary="Resumo", content="",
    )
    base.update(over)
    return ItemRecord(**base)


METAS = {
    f"w/{META_FILE}": {"name": "W", "description": "ws"},
    f"w/q/{META_FILE}": {"name": "Q", "subjects": [{"name": "git"}, {"name": "pix"}]},
}


def test_workspace_project_e_subject_vem_da_arvore():
    snap = Snapshot({}, METAS)
    assert snap.workspace("w").name == "W" and snap.workspace("w").description == "ws"
    assert snap.project("w", "q").name == "Q"
    assert {s.name for s in snap.subjects("w", "q")} == {"git", "pix"}


def test_subject_emerge_do_item():
    snap = Snapshot({"a": _rec(subject="Pagamentos")}, {})
    assert {s.name for s in snap.subjects("w", "q")} == {"Pagamentos"}


def test_item_pode_morar_no_workspace():
    # Item sem project mora no nível do workspace (novidade do v6).
    snap = Snapshot({"a": _rec(project=None)}, {})
    assert snap.get("a").project is None
    assert [r.id for r in snap.items_in("w")] == ["a"]


def test_tags_do_vocabulario_e_dos_itens():
    snap = Snapshot({"a": _rec(tags=["pix"])}, {META_FILE: {"tags": ["java"]}})
    assert [t.name for t in snap.tags()] == ["java", "pix"]


def test_view_do_item_v6_e_contadores_nos_dois_formatos(conn, data_dir, monkeypatch):
    store = FileStore(data_dir)
    store.write(_rec("novo", tags=["security"], links=[{"url": "https://d", "title": "D"}]))
    store.write(_rec("velho"))
    usage = {
        "novo": {"opened": 5, "last_used_at": "2026-02-01T10:00:00Z"},
        "velho": {"uses": 3, "last_used": "2026-01-05T10:00:00Z"},
    }
    monkeypatch.setattr(brain_mod.local_state, "get_usage", lambda _cid: usage)
    b = Brain()
    novo = b.view(b.snapshot.get("novo"))
    assert novo.type == "rule" and novo.tags == ["security"]
    assert novo.links == [{"url": "https://d", "title": "D"}]
    assert novo.access_count == 5 and novo.last_accessed == datetime(2026, 2, 1, 10, 0, 0)
    velho = b.view(b.snapshot.get("velho"))
    assert velho.access_count == 3 and velho.last_accessed == datetime(2026, 1, 5, 10, 0, 0)
    for gone in ("subtype", "scope", "effective_scope", "status", "origin", "ttl_days",
                 "scope_paths", "keywords", "source", "verified_at", "expires_at"):
        assert not hasattr(novo, gone)
