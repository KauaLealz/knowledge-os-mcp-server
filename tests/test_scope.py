"""Alcance (scope) dos itens: o resolvedor único (services/scope.py)."""

from datetime import datetime

from knowledge_os.services import scope
from knowledge_os.services.brain import META_FILE, Snapshot
from knowledge_os.storage.files import ItemRecord

W, P = "w", "p"  # repositório ligado a W/P


def _rec(id_: str, workspace: str, project: str, **over) -> ItemRecord:
    base = dict(
        id=id_, key=f"rule/{id_}", workspace=workspace, project=project, subject=None,
        type="rule", subtype=None, scope=None, title=f"Item {id_}", status="active", tags=[],
        links=[], scope_paths=[], ttl_days=None, keywords=None, source=None, origin="agent",
        verified_at=None, verified_commit=None, created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1), relations=[], summary="Resumo", content="",
        path=f"{workspace.lower()}/{project.lower()}/rule/{id_}.md",
    )
    base.update(over)
    return ItemRecord(**base)


def _snap(*records: ItemRecord, metas: dict | None = None) -> Snapshot:
    return Snapshot({r.id: r for r in records}, metas or {})


def test_mesmo_project_ve_tudo_com_distancia_1():
    snap = _snap(_rec("a", "W", "P"))
    assert scope.distance(snap, snap.get("a"), (W, P)) == 1.0


def test_item_scoped_de_outro_project_nao_aparece():
    snap = _snap(_rec("a", "W", "Q"))
    assert scope.distance(snap, snap.get("a"), (W, P)) is None


def test_workspace_global_aparece_para_repo_de_outro_workspace():
    metas = {f"e/{META_FILE}": {"name": "E", "scope": "global"}}
    snap = _snap(_rec("a", "E", "Q"), metas=metas)
    assert scope.distance(snap, snap.get("a"), (W, P)) == 0.7


def test_scope_explicito_do_item_vence_o_herdado():
    metas = {f"e/{META_FILE}": {"name": "E", "scope": "global"}}
    snap = _snap(_rec("a", "E", "Q", scope="scoped"), _rec("b", "W", "Q", scope="global"),
                 metas=metas)
    assert scope.distance(snap, snap.get("a"), (W, P)) is None
    assert scope.distance(snap, snap.get("b"), ("e", "q")) == 0.7


def test_subject_global_de_outro_workspace_aparece():
    metas = {f"w/q/{META_FILE}": {"name": "Q", "subjects": [{"name": "git", "scope": "global"}]}}
    snap = _snap(_rec("a", "W", "Q", subject="git"), _rec("b", "W", "Q"), metas=metas)
    assert scope.distance(snap, snap.get("a"), ("e", "x")) == 0.7
    assert scope.distance(snap, snap.get("b"), ("e", "x")) is None


def test_project_com_scope_workspace_aparece_so_no_mesmo_workspace():
    metas = {f"w/q/{META_FILE}": {"name": "Q", "scope": "workspace"}}
    snap = _snap(_rec("a", "W", "Q"), metas=metas)
    assert scope.distance(snap, snap.get("a"), (W, P)) == 0.85
    assert scope.distance(snap, snap.get("a"), ("e", "x")) is None


def test_pasta_nao_ligada_ve_so_global():
    metas = {f"w/q/{META_FILE}": {"name": "Q", "scope": "workspace"}}
    snap = _snap(_rec("a", "W", "Q"), _rec("b", "W", "P"), _rec("c", "W", "P", scope="global"),
                 metas=metas)
    assert [(r.id, d) for r, d in scope.reach(snap, None)] == [("c", 0.7)]


def test_reach_ordena_pela_distancia():
    snap = _snap(_rec("g", "E", "X", scope="global"), _rec("w", "W", "Q", scope="workspace"),
                 _rec("p", "W", "P"), _rec("n", "W", "Q"))
    assert [(r.id, d) for r, d in scope.reach(snap, (W, P))] == [
        ("p", 1.0), ("w", 0.85), ("g", 0.7)
    ]


def test_resolve_key_pela_cadeia():
    snap = _snap(
        _rec("local", "W", "P", key="rule/x"),
        _rec("ws", "W", "Q", key="rule/x", scope="workspace"),
        _rec("glob", "E", "X", key="rule/x", scope="global"),
        _rec("ws2", "W", "Q", key="rule/y", scope="workspace"),
        _rec("glob2", "E", "X", key="rule/y", scope="global"),
        _rec("glob3", "E", "X", key="rule/z", scope="global"),
        _rec("hidden", "E", "X", key="rule/h"),
    )
    assert scope.resolve_key(snap, "rule/x", (W, P)).id == "local"
    assert scope.resolve_key(snap, "rule/y", (W, P)).id == "ws2"
    assert scope.resolve_key(snap, "rule/z", (W, P)).id == "glob3"
    assert scope.resolve_key(snap, "rule/h", (W, P)) is None
    assert scope.resolve_key(snap, "rule/z", None).id == "glob3"
    assert scope.resolve_key(snap, "rule/x", None).id == "glob"
    assert scope.resolve_key(snap, "hidden", (W, P)).id == "hidden"  # por id
    assert scope.resolve_key(snap, "rule/nada", (W, P)) is None


def test_where_e_workspace_barra_project():
    assert scope.where(_rec("a", "Polara", "App Beta")) == "Polara/App Beta"
