"""Testes dos services de Workspace, Project e Subject (pastas e `.knowledge.yaml`)."""

import pytest

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.subject_service import SubjectService
from knowledge_os.services.workspace_service import WorkspaceService


def _item(ws, pj, key="k", subject=None, **extra):
    entry = {"workspace": ws, "project": pj, "key": key, "type": "knowledge", "title": "T",
             "summary": "s", "content": "c", **extra}
    if subject:
        entry["subject"] = subject
    return ItemService().save([entry])[0]["id"]


class TestWorkspaceService:
    def test_create_e_get(self, conn, data_dir):
        svc = WorkspaceService()
        ws = svc.create("Alpha Beta", "desc")
        assert ws.id == "alpha-beta" and ws.name == "Alpha Beta" and ws.description == "desc"
        assert svc.get("Alpha Beta").id == ws.id and svc.get("alpha-beta").name == "Alpha Beta"
        meta = (data_dir / "alpha-beta" / ".knowledge.yaml").read_text(encoding="utf-8")
        assert "name: Alpha Beta" in meta and "description: desc" in meta

    def test_create_duplicado_mesmo_slug(self, conn):
        svc = WorkspaceService()
        svc.create("alpha", None)
        with pytest.raises(ValidationError):
            svc.create("alpha", None)
        with pytest.raises(ValidationError):
            svc.create("ALPHA", None)

    def test_nome_sem_slug_e_recusado(self, conn):
        with pytest.raises(ValidationError):
            WorkspaceService().create("!!!", None)

    def test_get_inexistente(self, conn):
        with pytest.raises(NotFoundError):
            WorkspaceService().get("nada")

    def test_list_por_nome(self, conn):
        svc = WorkspaceService()
        for n in ("b", "a", "c"):
            svc.create(n, None)
        assert [w.name for w in svc.list()] == ["a", "b", "c"]

    def test_workspace_existe_so_pelos_itens(self, conn):
        _item("Só Itens", "app")
        assert [w.name for w in WorkspaceService().list()] == ["Só Itens"]

    def test_delete(self, sample_item, data_dir):
        svc = WorkspaceService()
        assert svc.delete("TestWorkspace") is True
        assert svc.delete("TestWorkspace") is False
        assert not (data_dir / "testworkspace").exists()
        assert svc.list() == []

    def test_export(self, sample_item):
        data = WorkspaceService().export("TestWorkspace")
        assert data["manifest"]["type"] == "workspace"
        assert data["manifest"]["counts"] == {"projects": 1, "items": 1}
        assert data["workspace_data"]["workspace"]["name"] == "TestWorkspace"
        assert data["workspace_data"]["projects"][0]["name"] == "TestProject"
        assert data["workspace_data"]["items"][0]["title"] == "Test Item"

    def test_export_inexistente(self, conn):
        with pytest.raises(NotFoundError):
            WorkspaceService().export("nada")

    def test_rename_move_a_pasta_e_regrava_os_itens(self, conn, data_dir):
        item_id = _item("alpha", "app", key="regra/x")
        svc = WorkspaceService()
        renamed = svc.rename("alpha", "Beta")
        assert renamed.id == "beta" and renamed.name == "Beta"
        assert svc.get("beta").name == "Beta"
        with pytest.raises(NotFoundError):
            svc.get("alpha")
        assert not (data_dir / "alpha").exists()
        text = (data_dir / "beta" / "app" / "regra" / "x.md").read_text(encoding="utf-8")
        assert "workspace: Beta" in text
        assert ItemService().get(item_id).workspace_id == "beta"

    def test_rename_so_da_caixa_mantem_a_pasta(self, conn, data_dir):
        _item("alpha", "app")
        WorkspaceService().rename("alpha", "Alpha")
        assert WorkspaceService().get("alpha").name == "Alpha"
        assert (data_dir / "alpha" / "app" / "k.md").is_file()

    def test_rename_colisao(self, conn):
        svc = WorkspaceService()
        svc.create("alpha", None)
        svc.create("beta", None)
        with pytest.raises(ValidationError):
            svc.rename("alpha", "beta")

    def test_rename_inexistente(self, conn):
        with pytest.raises(NotFoundError):
            WorkspaceService().rename("nada", "outro")

    def test_rename_leva_as_ligacoes_de_repositorio(self, conn):
        from knowledge_os.services.repo_service import RepoService

        RepoService().link("github.com/o/r", "alpha", "app")
        WorkspaceService().rename("alpha", "Beta")
        assert RepoService().resolve("github.com/o/r")["workspace"] == "Beta"

    def test_merge_sem_colisao(self, conn):
        svc = WorkspaceService()
        svc.create("src", None)
        svc.create("tgt", None)
        ProjectService().create("src", "p1", None)
        result = svc.merge("src", "tgt")
        assert result == {"merged_projects": 1, "renamed_collisions": 0}
        assert [p.name for p in ProjectService().list("tgt")] == ["p1"]
        with pytest.raises(NotFoundError):
            svc.get("src")

    def test_merge_com_colisao_de_nome(self, conn):
        svc = WorkspaceService()
        svc.create("src", None)
        svc.create("tgt", None)
        ProjectService().create("tgt", "shared", None)
        item_id = _item("src", "shared")

        result = svc.merge("src", "tgt")
        assert result == {"merged_projects": 1, "renamed_collisions": 1}
        assert [p.name for p in ProjectService().list("tgt")] == ["shared"]
        moved = ItemService().get(item_id)
        assert (moved.workspace_id, moved.project_id) == ("tgt", "shared")

    def test_merge_com_key_repetida_nao_grava_nada(self, conn):
        _item("src", "shared", key="k")
        _item("tgt", "shared", key="k")
        with pytest.raises(ValidationError, match="mesmo arquivo"):
            WorkspaceService().merge("src", "tgt")
        assert {w.name for w in WorkspaceService().list()} == {"src", "tgt"}


class TestProjectService:
    def test_create_get_list(self, sample_workspace):
        svc = ProjectService()
        d = svc.create(sample_workspace.id, "d1", None)
        assert d.id == "d1" and d.workspace_id == sample_workspace.id
        assert svc.get(sample_workspace.id, "d1").id == d.id
        assert [x.name for x in svc.list(sample_workspace.id)] == ["d1"]

    def test_create_workspace_inexistente(self, conn):
        with pytest.raises(NotFoundError):
            ProjectService().create("x", "d1", None)

    def test_create_duplicado(self, sample_project):
        with pytest.raises(ValidationError):
            ProjectService().create(sample_project.workspace_id, "TestProject", None)

    def test_get_inexistente(self, sample_workspace):
        with pytest.raises(NotFoundError):
            ProjectService().get(sample_workspace.id, "nada")

    def test_delete(self, sample_item, data_dir):
        svc = ProjectService()
        wid = sample_item.workspace_id
        assert svc.delete(wid, "TestProject") is True
        assert svc.delete(wid, "TestProject") is False
        assert not (data_dir / "testworkspace" / "testproject").exists()

    def test_export(self, sample_item):
        data = ProjectService().export(sample_item.workspace_id, "TestProject")
        assert data["project_data"]["project"]["name"] == "TestProject"
        assert data["project_data"]["items"][0]["title"] == "Test Item"

    def test_rename(self, sample_workspace):
        svc = ProjectService()
        svc.create(sample_workspace.id, "d1", None)
        renamed = svc.rename(sample_workspace.id, "d1", "d2")
        assert renamed.id == "d2" and renamed.name == "d2"
        assert svc.get(sample_workspace.id, "d2").name == "d2"
        with pytest.raises(NotFoundError):
            svc.get(sample_workspace.id, "d1")

    def test_rename_colisao(self, sample_workspace):
        svc = ProjectService()
        svc.create(sample_workspace.id, "d1", None)
        svc.create(sample_workspace.id, "d2", None)
        with pytest.raises(ValidationError):
            svc.rename(sample_workspace.id, "d1", "d2")

    def test_merge_sem_colisao(self, conn):
        item_id = _item("W", "src")
        ProjectService().create("w", "tgt", None)
        result = ProjectService().merge("w", "src", "tgt")
        assert result == {"merged_items": 1, "merged_subjects": 0}
        assert ItemService().get(item_id).project_id == "tgt"
        with pytest.raises(NotFoundError):
            ProjectService().get("w", "src")

    def test_merge_com_colisao_de_subject(self, conn):
        item_id = _item("W", "src", subject="shared")
        _item("W", "tgt", key="outro", subject="shared")
        SubjectService().create("w", "src", "only-in-src", None)

        result = ProjectService().merge("w", "src", "tgt")
        assert result == {"merged_items": 1, "merged_subjects": 1}
        assert ItemService().get(item_id).subject_id == "shared"
        assert SubjectService().get("w", "tgt", "only-in-src").name == "only-in-src"

    def test_mesmo_project_em_workspaces_diferentes(self, conn):
        _item("A", "geral")
        _item("B", "geral")
        svc = ProjectService()
        with pytest.raises(ValidationError, match="mais de um workspace"):
            svc.find_by_id("geral")
        assert svc.find_by_id("geral", "b").workspace_id == "b"


class TestSubjectService:
    def test_create_get_list(self, sample_project):
        svc = SubjectService()
        ws = sample_project.workspace_id
        sj = svc.create(ws, sample_project.id, "backend", "assuntos de backend")
        assert sj.id == "backend" and sj.name == "backend"
        assert sj.description == "assuntos de backend"
        assert svc.get(ws, sample_project.id, "backend").id == sj.id
        assert [x.name for x in svc.list(ws, sample_project.id)] == ["backend"]

    def test_create_project_inexistente(self, sample_workspace):
        with pytest.raises(NotFoundError):
            SubjectService().create(sample_workspace.id, "project-que-nao-existe", "s1", None)

    def test_unicidade_por_project_e_nome(self, sample_project):
        svc = SubjectService()
        svc.create(sample_project.workspace_id, sample_project.id, "s1", None)
        with pytest.raises(ValidationError):
            svc.create(sample_project.workspace_id, sample_project.id, "s1", None)

    def test_mesmo_nome_em_projects_diferentes_nao_colide(self, sample_project):
        ws = sample_project.workspace_id
        outro = ProjectService().create(ws, "outro-project")
        svc = SubjectService()
        svc.create(ws, sample_project.id, "s1", None)
        sj2 = svc.create(ws, outro.id, "s1", None)
        assert sj2.project_id == outro.id

    def test_get_inexistente(self, sample_project):
        with pytest.raises(NotFoundError):
            SubjectService().get(sample_project.workspace_id, sample_project.id, "nada")

    def test_delete_inexistente_retorna_false(self, sample_project):
        assert SubjectService().delete(sample_project.workspace_id, sample_project.id,
                                       "nada") is False

    def test_delete_desvincula_items_em_vez_de_apagar(self, conn):
        item_id = _item("W", "D", subject="s1")
        svc = SubjectService()
        assert svc.delete("w", "d", "s1") is True
        assert svc.delete("w", "d", "s1") is False
        item = ItemService().get(item_id)  # o item continua existindo
        assert item.subject_id is None  # só desvinculado

    def test_rename(self, conn):
        item_id = _item("W", "D", subject="s1")
        svc = SubjectService()
        renamed = svc.rename("w", "d", "s1", "s2")
        assert renamed.id == "s2" and renamed.name == "s2"
        assert ItemService().get(item_id).subject == "s2"

    def test_rename_colisao(self, sample_project):
        svc = SubjectService()
        ws = sample_project.workspace_id
        svc.create(ws, sample_project.id, "s1", None)
        svc.create(ws, sample_project.id, "s2", None)
        with pytest.raises(ValidationError):
            svc.rename(ws, sample_project.id, "s1", "s2")

    def test_merge(self, conn):
        item_id = _item("W", "D", subject="src")
        SubjectService().create("w", "d", "tgt", None)
        result = SubjectService().merge("w", "d", "src", "tgt")
        assert result == {"merged_items": 1}
        assert ItemService().get(item_id).subject == "tgt"
        with pytest.raises(NotFoundError):
            SubjectService().get("w", "d", "src")
