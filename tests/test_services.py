"""Testes dos services de Workspace e Project."""

import pytest
from sqlalchemy.orm import Session

from knowledge_os.db.models import Item, Project, Workspace
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.project_service import ProjectService
from knowledge_os.services.subject_service import SubjectService
from knowledge_os.services.workspace_service import WorkspaceService


class TestWorkspaceService:
    def test_create_e_get(self, test_session: Session):
        svc = WorkspaceService(test_session)
        ws = svc.create("alpha", "desc")
        assert ws.id and ws.name == "alpha" and ws.description == "desc"
        assert svc.get("alpha").id == ws.id

    def test_create_duplicado(self, test_session: Session):
        svc = WorkspaceService(test_session)
        svc.create("alpha", None)
        with pytest.raises(ValidationError):
            svc.create("alpha", None)

    def test_get_inexistente(self, test_session: Session):
        with pytest.raises(NotFoundError):
            WorkspaceService(test_session).get("nada")

    def test_list_ordenada(self, test_session: Session):
        svc = WorkspaceService(test_session)
        for n in ("b", "a", "c"):
            svc.create(n, None)
        assert [w.name for w in svc.list()] == ["b", "a", "c"]

    def test_delete(self, test_session: Session, sample_project: Project):
        svc = WorkspaceService(test_session)
        assert svc.delete("TestWorkspace") is True
        assert svc.delete("TestWorkspace") is False
        assert test_session.query(Project).count() == 0

    def test_export(self, test_session: Session, sample_item):
        data = WorkspaceService(test_session).export("TestWorkspace")
        assert data["manifest"]["type"] == "workspace"
        assert data["manifest"]["counts"] == {"projects": 1, "items": 1}
        assert data["workspace_data"]["workspace"]["name"] == "TestWorkspace"
        assert data["workspace_data"]["projects"][0]["name"] == "TestProject"
        assert data["workspace_data"]["items"][0]["title"] == "Test Item"

    def test_export_inexistente(self, test_session: Session):
        with pytest.raises(NotFoundError):
            WorkspaceService(test_session).export("nada")

    def test_rename(self, test_session: Session):
        svc = WorkspaceService(test_session)
        ws = svc.create("alpha", None)
        renamed = svc.rename("alpha", "beta")
        assert renamed.id == ws.id and renamed.name == "beta"
        assert svc.get("beta").id == ws.id
        with pytest.raises(NotFoundError):
            svc.get("alpha")

    def test_rename_colisao(self, test_session: Session):
        svc = WorkspaceService(test_session)
        svc.create("alpha", None)
        svc.create("beta", None)
        with pytest.raises(ValidationError):
            svc.rename("alpha", "beta")

    def test_rename_inexistente(self, test_session: Session):
        with pytest.raises(NotFoundError):
            WorkspaceService(test_session).rename("nada", "outro")

    def test_merge_sem_colisao(self, test_session: Session):
        svc = WorkspaceService(test_session)
        src = svc.create("src", None)
        tgt = svc.create("tgt", None)
        ProjectService(test_session).create(src.id, "p1", None)
        result = svc.merge("src", "tgt")
        assert result == {"merged_projects": 1, "renamed_collisions": 0}
        assert [p.name for p in ProjectService(test_session).list(tgt.id)] == ["p1"]
        with pytest.raises(NotFoundError):
            svc.get("src")

    def test_merge_com_colisao_de_nome(self, test_session: Session):
        svc = WorkspaceService(test_session)
        src = svc.create("src", None)
        tgt = svc.create("tgt", None)
        project_svc = ProjectService(test_session)
        src_project = project_svc.create(src.id, "shared", None)
        tgt_project = project_svc.create(tgt.id, "shared", None)
        item = Item(
            id="i1", workspace_id=src.id, project_id=src_project.id, type="knowledge",
            memory_class="longterm", title="T", summary="s", content="c",
        )
        test_session.add(item)
        test_session.commit()

        result = svc.merge("src", "tgt")
        assert result == {"merged_projects": 1, "renamed_collisions": 1}
        remaining = project_svc.list(tgt.id)
        assert [p.name for p in remaining] == ["shared"]
        assert test_session.get(Item, "i1").project_id == tgt_project.id


class TestProjectService:
    def test_create_get_list(self, test_session: Session, sample_workspace: Workspace):
        svc = ProjectService(test_session)
        d = svc.create(sample_workspace.id, "d1", None)
        assert svc.get(sample_workspace.id, "d1").id == d.id
        assert [x.name for x in svc.list(sample_workspace.id)] == ["d1"]

    def test_create_workspace_inexistente(self, test_session: Session):
        with pytest.raises(NotFoundError):
            ProjectService(test_session).create("x", "d1", None)

    def test_create_duplicado(self, test_session: Session, sample_project: Project):
        with pytest.raises(ValidationError):
            ProjectService(test_session).create(sample_project.workspace_id, "TestProject", None)

    def test_get_inexistente(self, test_session: Session, sample_workspace: Workspace):
        with pytest.raises(NotFoundError):
            ProjectService(test_session).get(sample_workspace.id, "nada")

    def test_delete(self, test_session: Session, sample_item):
        svc = ProjectService(test_session)
        wid = sample_item.workspace_id
        assert svc.delete(wid, "TestProject") is True
        assert svc.delete(wid, "TestProject") is False

    def test_export(self, test_session: Session, sample_item):
        data = ProjectService(test_session).export(sample_item.workspace_id, "TestProject")
        assert data["project_data"]["project"]["name"] == "TestProject"
        assert data["project_data"]["items"][0]["title"] == "Test Item"

    def test_rename(self, test_session: Session, sample_workspace: Workspace):
        svc = ProjectService(test_session)
        p = svc.create(sample_workspace.id, "d1", None)
        renamed = svc.rename(sample_workspace.id, "d1", "d2")
        assert renamed.id == p.id and renamed.name == "d2"
        assert svc.get(sample_workspace.id, "d2").id == p.id

    def test_rename_colisao(self, test_session: Session, sample_workspace: Workspace):
        svc = ProjectService(test_session)
        svc.create(sample_workspace.id, "d1", None)
        svc.create(sample_workspace.id, "d2", None)
        with pytest.raises(ValidationError):
            svc.rename(sample_workspace.id, "d1", "d2")

    def test_merge_sem_colisao(self, test_session: Session, sample_workspace: Workspace):
        svc = ProjectService(test_session)
        src = svc.create(sample_workspace.id, "src", None)
        tgt = svc.create(sample_workspace.id, "tgt", None)
        item = Item(
            id="i1", workspace_id=sample_workspace.id, project_id=src.id, type="knowledge",
            memory_class="longterm", title="T", summary="s", content="c",
        )
        test_session.add(item)
        test_session.commit()

        result = svc.merge(sample_workspace.id, "src", "tgt")
        assert result == {"merged_items": 1, "merged_subjects": 0}
        assert test_session.get(Item, "i1").project_id == tgt.id
        with pytest.raises(NotFoundError):
            svc.get(sample_workspace.id, "src")

    def test_merge_com_colisao_de_subject(self, test_session: Session, sample_workspace: Workspace):
        svc = ProjectService(test_session)
        src = svc.create(sample_workspace.id, "src", None)
        tgt = svc.create(sample_workspace.id, "tgt", None)
        subject_svc = SubjectService(test_session)
        src_subj = subject_svc.create(src.id, "shared", None)
        tgt_subj = subject_svc.create(tgt.id, "shared", None)
        src_only_subj = subject_svc.create(src.id, "only-in-src", None)
        item = Item(
            id="i1", workspace_id=sample_workspace.id, project_id=src.id, subject_id=src_subj.id,
            type="knowledge", memory_class="longterm", title="T", summary="s", content="c",
        )
        test_session.add(item)
        test_session.commit()

        result = svc.merge(sample_workspace.id, "src", "tgt")
        assert result == {"merged_items": 1, "merged_subjects": 1}
        assert test_session.get(Item, "i1").subject_id == tgt_subj.id
        assert subject_svc.get(tgt.id, "only-in-src").id == src_only_subj.id


class TestSubjectService:
    def test_create_get_list(self, test_session: Session, sample_project: Project):
        svc = SubjectService(test_session)
        sj = svc.create(sample_project.id, "s1", None)
        assert svc.get(sample_project.id, "s1").id == sj.id
        assert [x.name for x in svc.list(sample_project.id)] == ["s1"]

    def test_create_project_inexistente(self, test_session: Session):
        with pytest.raises(NotFoundError):
            SubjectService(test_session).create("x", "s1", None)

    def test_create_duplicado(self, test_session: Session, sample_project: Project):
        SubjectService(test_session).create(sample_project.id, "s1", None)
        with pytest.raises(ValidationError):
            SubjectService(test_session).create(sample_project.id, "s1", None)

    def test_get_inexistente(self, test_session: Session, sample_project: Project):
        with pytest.raises(NotFoundError):
            SubjectService(test_session).get(sample_project.id, "nada")

    def test_delete_desvincula_items_em_vez_de_apagar(
        self, test_session: Session, sample_item: Item
    ):
        svc = SubjectService(test_session)
        sj = svc.create(sample_item.project_id, "s1", None)
        sample_item.subject_id = sj.id
        test_session.commit()

        assert svc.delete(sample_item.project_id, "s1") is True
        assert svc.delete(sample_item.project_id, "s1") is False

        item = test_session.get(Item, sample_item.id)
        assert item is not None
        assert item.subject_id is None

    def test_rename(self, test_session: Session, sample_project: Project):
        svc = SubjectService(test_session)
        sj = svc.create(sample_project.id, "s1", None)
        renamed = svc.rename(sample_project.id, "s1", "s2")
        assert renamed.id == sj.id and renamed.name == "s2"
        assert svc.get(sample_project.id, "s2").id == sj.id

    def test_rename_colisao(self, test_session: Session, sample_project: Project):
        svc = SubjectService(test_session)
        svc.create(sample_project.id, "s1", None)
        svc.create(sample_project.id, "s2", None)
        with pytest.raises(ValidationError):
            svc.rename(sample_project.id, "s1", "s2")

    def test_merge(self, test_session: Session, sample_item: Item):
        svc = SubjectService(test_session)
        src = svc.create(sample_item.project_id, "src", None)
        tgt = svc.create(sample_item.project_id, "tgt", None)
        sample_item.subject_id = src.id
        test_session.commit()

        result = svc.merge(sample_item.project_id, "src", "tgt")
        assert result == {"merged_items": 1}
        assert test_session.get(Item, sample_item.id).subject_id == tgt.id
        with pytest.raises(NotFoundError):
            svc.get(sample_item.project_id, "src")
