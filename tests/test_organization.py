"""Organização v2 (V2_MVP.md §4, §9): `scope` em workspace/project/subject (create, update,
merge), `update` no lugar de `rename`, `rows()` para os `*_list` e a herança vista pelo
`Snapshot` (o alcance muda sem mover arquivo de item)."""

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services import scope as scope_mod
from knowledge_os.services.brain import Brain
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.subject_service import SubjectService
from knowledge_os.services.workspace_service import WorkspaceService


def _item(ws, pj, key="rule/x", subject=None, **extra):
    entry = {"workspace": ws, "project": pj, "key": key, "type": "rule", "title": "T",
             "summary": "s", "content": "c", **extra}
    if subject:
        entry["subject"] = subject
    return ItemService().save([entry])[0]["id"]


def _meta(data_dir, *parts):
    return (data_dir.joinpath(*parts) / ".knowledge.yaml").read_text(encoding="utf-8")


def _effective(item_id):
    snap = Brain().snapshot
    return snap.effective_scope(snap.require(item_id))


def _md_files(data_dir):
    return sorted(p.relative_to(data_dir).as_posix() for p in data_dir.rglob("*.md")
                  if ".git" not in p.parts)


# ---- create com scope -----------------------------------------------------------------------


def test_create_grava_scope_no_knowledge_yaml(conn, data_dir):
    ws = WorkspaceService().create("E", "empresa", scope="global")
    assert ws.scope == "global" and "scope: global" in _meta(data_dir, "e")
    pj = ProjectService().create("e", "Q", scope="workspace")
    assert pj.scope == "workspace" and "scope: workspace" in _meta(data_dir, "e", "q")
    sj = SubjectService().create("e", "q", "git", "comandos", scope="global")
    assert sj.scope == "global" and sj.description == "comandos"
    meta = _meta(data_dir, "e", "q")
    assert "name: git" in meta and "description: comandos" in meta


def test_create_sem_scope_nao_define_e_herda(conn, data_dir):
    WorkspaceService().create("E", scope="global")
    pj = ProjectService().create("e", "Q")
    assert pj.scope is None and "scope" not in _meta(data_dir, "e", "q")
    assert _effective(_item("E", "Q")) == "global"


@pytest.mark.parametrize("call", [
    lambda: WorkspaceService().create("E", scope="projeto"),
    lambda: ProjectService().create("e", "Q", scope="todos"),
    lambda: SubjectService().create("e", "q", "s", scope="x"),
])
def test_scope_invalido_lista_os_validos(conn, call):
    WorkspaceService().create("E")
    ProjectService().create("e", "Q")
    with pytest.raises(ValidationError, match="scoped, workspace, global"):
        call()


# ---- update ---------------------------------------------------------------------------------


def test_workspace_update_scope_muda_o_alcance_sem_mover_arquivo(conn, data_dir):
    item_id = _item("E", "Q")
    before = _md_files(data_dir)
    assert scope_mod.distance(Brain().snapshot, Brain().snapshot.require(item_id),
                              ("w", "p")) is None
    ws = WorkspaceService().update("E", scope="global")
    assert ws.scope == "global" and ws.name == "E"
    snap = Brain().snapshot
    assert scope_mod.distance(snap, snap.require(item_id), ("w", "p")) == scope_mod.ELSEWHERE
    assert _md_files(data_dir) == before


def test_project_update_scope_workspace_vale_no_workspace_e_nao_fora(conn):
    item_id = _item("W", "Q")
    ProjectService().update("w", "Q", scope="workspace")
    snap = Brain().snapshot
    record = snap.require(item_id)
    assert scope_mod.distance(snap, record, ("w", "p")) == scope_mod.SAME_WORKSPACE
    assert scope_mod.distance(snap, record, ("e", "x")) is None


def test_subject_update_scope_global_aparece_em_outro_workspace(conn, data_dir):
    item_id = _item("W", "Q", subject="git")
    sj = SubjectService().update("w", "q", "git", scope="global")
    assert sj.scope == "global"
    assert "scope: global" in _meta(data_dir, "w", "q")
    snap = Brain().snapshot
    assert scope_mod.distance(snap, snap.require(item_id), ("e", "x")) == scope_mod.ELSEWHERE


def test_scope_explicito_no_project_vence_o_do_workspace(conn):
    item_id = _item("E", "Q")
    WorkspaceService().update("E", scope="global")
    ProjectService().update("e", "q", scope="scoped")
    assert _effective(item_id) == "scoped"


def test_update_scope_vazio_volta_a_herdar(conn, data_dir):
    item_id = _item("E", "Q")
    WorkspaceService().update("E", scope="global")
    ProjectService().update("e", "q", scope="scoped")
    ProjectService().update("e", "q", scope="")
    assert "scope" not in _meta(data_dir, "e", "q") and _effective(item_id) == "global"


def test_update_scope_invalido(conn):
    _item("E", "Q", subject="s")
    for call in (lambda: WorkspaceService().update("E", scope="x"),
                 lambda: ProjectService().update("e", "q", scope="x"),
                 lambda: SubjectService().update("e", "q", "s", scope="x")):
        with pytest.raises(ValidationError, match="scoped, workspace, global"):
            call()


def test_update_nome_descricao_e_scope_juntos(conn, data_dir):
    _item("E", "Q")
    ws = WorkspaceService().update("E", new_name="Empresa", description="d", scope="workspace")
    assert (ws.id, ws.name, ws.description, ws.scope) == ("empresa", "Empresa", "d", "workspace")
    pj = ProjectService().update("empresa", "Q", new_name="Q2", description="dq", scope="global")
    assert (pj.id, pj.name, pj.description, pj.scope) == ("q2", "Q2", "dq", "global")
    meta = _meta(data_dir, "empresa", "q2")
    assert "name: Q2" in meta and "scope: global" in meta


def test_update_so_descricao_mantem_nome_e_scope(conn):
    WorkspaceService().create("E", scope="global")
    ws = WorkspaceService().update("E", description="nova")
    assert (ws.name, ws.description, ws.scope) == ("E", "nova", "global")


def test_subject_update_renomeia_e_mantem_scope(conn):
    item_id = _item("W", "P", subject="s1")
    SubjectService().update("w", "p", "s1", scope="global")
    sj = SubjectService().update("w", "p", "s1", new_name="s2")
    assert (sj.name, sj.scope) == ("s2", "global")
    assert ItemService().get(item_id).subject == "s2"
    assert _effective(item_id) == "global"


def test_rename_saiu(conn):
    for svc in (WorkspaceService(), ProjectService(), SubjectService()):
        assert not hasattr(svc, "rename")
        assert not hasattr(svc, "export")


# ---- merge mantém o scope -------------------------------------------------------------------


def test_workspace_merge_leva_o_scope_do_project(conn):
    WorkspaceService().create("Src")
    WorkspaceService().create("Tgt")
    ProjectService().create("src", "P", scope="global")
    WorkspaceService().merge("Src", "Tgt")
    assert ProjectService().get("tgt", "p").scope == "global"


def test_project_merge_scope_do_destino_prevalece(conn):
    _item("W", "Src")
    ProjectService().create("w", "Tgt", scope="workspace")
    ProjectService().update("w", "Src", scope="global")
    SubjectService().create("w", "src", "git", scope="global")
    ProjectService().merge("w", "Src", "Tgt")
    assert ProjectService().get("w", "tgt").scope == "workspace"
    assert SubjectService().get("w", "tgt", "git").scope == "global"


def test_workspace_merge_com_colisao_scope_do_destino(conn):
    WorkspaceService().create("Src")
    WorkspaceService().create("Tgt")
    ProjectService().create("src", "P", scope="global")
    ProjectService().create("tgt", "P", scope="workspace")
    WorkspaceService().merge("Src", "Tgt")
    assert ProjectService().get("tgt", "p").scope == "workspace"


def test_subject_merge_scope_do_destino_prevalece(conn):
    _item("W", "P", subject="a")
    SubjectService().create("w", "p", "b", scope="workspace")
    SubjectService().update("w", "p", "a", scope="global")
    SubjectService().merge("w", "p", "a", "b")
    assert SubjectService().get("w", "p", "b").scope == "workspace"


# ---- rows -----------------------------------------------------------------------------------


def test_workspace_rows(conn):
    WorkspaceService().create("E", "empresa", scope="global")
    _item("E", "Q")
    _item("E", "R", key="rule/y")
    WorkspaceService().create("Vazio")
    rows = WorkspaceService().rows()
    assert rows == [
        {"id": "e", "name": "E", "description": "empresa", "scope": "global",
         "scope_explicit": "global", "items": 2, "projects": 2},
        {"id": "vazio", "name": "Vazio", "description": None, "scope": "scoped",
         "scope_explicit": None, "items": 0, "projects": 0},
    ]


def test_project_rows_com_subjects_e_scope_herdado(conn):
    WorkspaceService().create("E", scope="workspace")
    _item("E", "Q", subject="git")
    _item("E", "Q", key="rule/y")
    ProjectService().create("e", "R", "outro", scope="global")
    SubjectService().create("e", "q", "api")
    rows = ProjectService().rows("E")
    assert rows == [
        {"id": "q", "workspace_id": "e", "name": "Q", "description": None,
         "scope": "workspace", "scope_explicit": None, "items": 2, "subjects": ["api", "git"]},
        {"id": "r", "workspace_id": "e", "name": "R", "description": "outro",
         "scope": "global", "scope_explicit": "global", "items": 0, "subjects": []},
    ]


def test_subject_rows(conn):
    ProjectService().create(WorkspaceService().create("W").id, "P", scope="workspace")
    _item("W", "P", subject="git")
    SubjectService().create("w", "p", "api", "rotas", scope="global")
    rows = SubjectService().rows("W", "P")
    assert rows == [
        {"id": "api", "name": "api", "description": "rotas", "scope": "global",
         "scope_explicit": "global", "items": 0},
        {"id": "git", "name": "git", "description": None, "scope": "workspace",
         "scope_explicit": None, "items": 1},
    ]
