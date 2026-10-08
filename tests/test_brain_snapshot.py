"""Snapshot v2: scope herdado do `.knowledge.yaml`, tags sem labels, vencimento por ttl e a
visão do item (services/brain.py)."""

from datetime import datetime, timedelta

import yaml

from knowledge_os.services import brain as brain_mod
from knowledge_os.services.brain import META_FILE, Brain, Draft, Snapshot, expires_at, is_expired
from knowledge_os.storage.files import FileStore, ItemRecord


def _rec(id_: str = "a", workspace: str = "W", project: str = "Q", **over) -> ItemRecord:
    base = dict(
        id=id_, key=f"rule/{id_}", workspace=workspace, project=project, subject=None,
        type="rule", subtype=None, scope=None, title="Titulo", status="active", tags=[],
        links=[], scope_paths=[], ttl_days=None, keywords=None, source=None, origin="agent",
        verified_at=None, verified_commit=None, created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1), relations=[], summary="Resumo", content="",
    )
    base.update(over)
    return ItemRecord(**base)


METAS = {
    f"w/{META_FILE}": {"name": "W", "description": "ws", "scope": "global"},
    f"w/q/{META_FILE}": {"name": "Q", "scope": "workspace",
                         "subjects": [{"name": "git", "scope": "scoped"}, {"name": "pix"}]},
}


def test_workspace_project_e_subject_trazem_o_scope_do_yaml():
    snap = Snapshot({}, METAS)
    assert snap.workspace("w").scope == "global"
    assert snap.project("w", "q").scope == "workspace"
    assert {s.name: s.scope for s in snap.subjects("w", "q")} == {"git": "scoped", "pix": None}


def test_scope_invalido_no_yaml_e_ignorado():
    snap = Snapshot({}, {f"w/{META_FILE}": {"name": "W", "scope": "todo-lugar"}})
    assert snap.workspace("w").scope is None


def test_effective_scope_sobe_item_subject_project_workspace():
    snap = Snapshot({}, METAS)
    assert snap.effective_scope(_rec(scope="global", subject="git")) == "global"
    assert snap.effective_scope(_rec(subject="git")) == "scoped"
    assert snap.effective_scope(_rec(subject="pix")) == "workspace"
    assert snap.effective_scope(_rec(project="Outro")) == "global"
    assert snap.effective_scope(_rec(workspace="Livre", project="X")) == "scoped"


def test_scope_preservado_ao_regravar_metas():
    draft = Draft(Snapshot({}, METAS))
    rel = f"w/q/{META_FILE}"
    meta = draft.meta(rel)
    meta["description"] = "nova"
    draft.set_meta(rel, meta)
    written = yaml.safe_load(draft.files()[rel])
    assert written["scope"] == "workspace"
    assert written["subjects"][0] == {"name": "git", "scope": "scoped"}


def test_tags_do_vocabulario_e_dos_itens_sem_labels():
    snap = Snapshot({"a": _rec(tags=["pix"])}, {META_FILE: {"tags": ["java"], "labels": ["x"]}})
    assert [t.name for t in snap.tags()] == ["java", "pix"]
    assert not hasattr(snap, "labels")


def test_vencimento_por_ttl_em_qualquer_tipo():
    updated = datetime(2026, 1, 1)
    record = _rec(type="context", ttl_days=7, updated_at=updated)
    assert expires_at(record) == updated + timedelta(days=7)
    assert is_expired(record, now=updated + timedelta(days=8))
    assert not is_expired(record, now=updated + timedelta(days=6))
    assert expires_at(_rec()) is None and not is_expired(_rec())


def test_view_do_item_v2_e_contadores_nos_dois_formatos(conn, data_dir, monkeypatch):
    store = FileStore(data_dir)
    store.write(_rec("novo", subtype="security", links=[{"title": "D", "url": "https://d"}],
                     origin="user"))
    store.write(_rec("velho"))
    usage = {
        "novo": {"opened": 5, "last_used_at": "2026-02-01T10:00:00Z"},
        "velho": {"uses": 3, "last_used": "2026-01-05T10:00:00Z"},
    }
    monkeypatch.setattr(brain_mod.local_state, "get_usage", lambda _cid: usage)
    (data_dir / "w" / "q" / META_FILE).write_text("name: Q\nscope: workspace\n",
                                                   encoding="utf-8")
    b = Brain()
    novo = b.view(b.snapshot.get("novo"))
    assert (novo.subtype, novo.scope, novo.effective_scope, novo.origin) == (
        "security", None, "workspace", "user")
    assert novo.links == [{"title": "D", "url": "https://d"}]
    assert novo.access_count == 5 and novo.last_accessed == datetime(2026, 2, 1, 10, 0, 0)
    velho = b.view(b.snapshot.get("velho"))
    assert velho.access_count == 3 and velho.last_accessed == datetime(2026, 1, 5, 10, 0, 0)
    for gone in ("memory_class", "labels", "importance", "confidence"):
        assert not hasattr(novo, gone)
