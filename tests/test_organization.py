"""Organização v6: workspace/project/subject por nome e descrição (create, update, merge),
`rows()` para os `*_list`. Sem scope (o alcance vem da hierarquia; ver test_scope.py)."""

import pytest

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


# ---- create / update ------------------------------------------------------------------------


def test_create_grava_nome_e_descricao(conn, data_dir):
    WorkspaceService().create("E", "empresa")
    assert "name: E" in _meta(data_dir, "e") and "description: empresa" in _meta(data_dir, "e")
    ProjectService().create("e", "Q", "proj")
    assert "name: Q" in _meta(data_dir, "e", "q")
    sj = SubjectService().create("e", "q", "git", "comandos")
    assert sj.name == "git" and sj.description == "comandos"
    assert "name: git" in _meta(data_dir, "e", "q")


def test_update_nome_e_descricao(conn):
    WorkspaceService().create("E")
    ws = WorkspaceService().update("E", new_name="Empresa", description="d")
    assert (ws.id, ws.name, ws.description) == ("empresa", "Empresa", "d")
    pj = ProjectService().create("empresa", "Q")
    pj = ProjectService().update("empresa", "Q", new_name="Q2", description="dq")
    assert (pj.id, pj.name, pj.description) == ("q2", "Q2", "dq")


def test_update_so_descricao_mantem_nome(conn):
    WorkspaceService().create("E")
    ws = WorkspaceService().update("E", description="nova")
    assert (ws.name, ws.description) == ("E", "nova")


def test_subject_update_renomeia(conn):
    item_id = _item("W", "P", subject="s1")
    sj = SubjectService().update("w", "p", "s1", new_name="s2")
    assert sj.name == "s2"
    assert ItemService().get(item_id).subject == "s2"


def test_rename_e_export_sairam(conn):
    for svc in (WorkspaceService(), ProjectService(), SubjectService()):
        assert not hasattr(svc, "rename")
        assert not hasattr(svc, "export")


# ---- merge ----------------------------------------------------------------------------------


def test_workspace_merge_leva_os_projects(conn):
    WorkspaceService().create("Src")
    WorkspaceService().create("Tgt")
    ProjectService().create("src", "P")
    WorkspaceService().merge("Src", "Tgt")
    assert ProjectService().get("tgt", "p").name == "P"


def test_project_merge_junta_os_itens(conn):
    _item("W", "Src")
    ProjectService().create("w", "Tgt")
    ProjectService().merge("w", "Src", "Tgt")
    assert any(r.project == "Tgt" for r in Brain().snapshot.items_in("w", "tgt"))


def test_subject_merge(conn):
    _item("W", "P", subject="a")
    SubjectService().create("w", "p", "b")
    SubjectService().merge("w", "p", "a", "b")
    assert SubjectService().get("w", "p", "b").name == "b"


# ---- rows -----------------------------------------------------------------------------------


def test_workspace_rows_sem_scope(conn):
    WorkspaceService().create("E", "empresa")
    _item("E", "Q")
    _item("E", "R", key="rule/y")
    WorkspaceService().create("Vazio")
    rows = WorkspaceService().rows()
    by_id = {r["id"]: r for r in rows}
    assert by_id["e"]["name"] == "E" and by_id["e"]["items"] == 2 and by_id["e"]["projects"] == 2
    assert by_id["vazio"]["items"] == 0
    for r in rows:
        assert "scope" not in r and "scope_explicit" not in r


def test_project_rows_com_subjects(conn):
    WorkspaceService().create("E")
    _item("E", "Q", subject="git")
    _item("E", "Q", key="rule/y")
    SubjectService().create("e", "q", "api")
    rows = ProjectService().rows("E")
    q = next(r for r in rows if r["id"] == "q")
    assert q["items"] == 2 and sorted(q["subjects"]) == ["api", "git"]
    assert "scope" not in q


def test_subject_rows_sem_scope(conn):
    ProjectService().create(WorkspaceService().create("W").id, "P")
    _item("W", "P", subject="git")
    SubjectService().create("w", "p", "api", "rotas")
    rows = SubjectService().rows("W", "P")
    by_id = {r["id"]: r for r in rows}
    assert by_id["git"]["items"] == 1 and by_id["api"]["description"] == "rotas"
    for r in rows:
        assert "scope" not in r


@pytest.mark.parametrize("call", [
    lambda: WorkspaceService().create("E"),
])
def test_smoke_create(conn, call):
    assert call()
