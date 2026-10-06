"""Testes dos services de Workspace e Project."""

import pytest
from sqlalchemy.orm import Session

from knowledge_os.db.models import Project, Workspace
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.project_service import ProjectService
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
        assert data["workspace_data"]["projects"][0]["name"] == "TestDomain"
        assert data["workspace_data"]["items"][0]["title"] == "Test Item"

    def test_export_inexistente(self, test_session: Session):
        with pytest.raises(NotFoundError):
            WorkspaceService(test_session).export("nada")


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
            ProjectService(test_session).create(sample_project.workspace_id, "TestDomain", None)

    def test_get_inexistente(self, test_session: Session, sample_workspace: Workspace):
        with pytest.raises(NotFoundError):
            ProjectService(test_session).get(sample_workspace.id, "nada")

    def test_delete(self, test_session: Session, sample_item):
        svc = ProjectService(test_session)
        wid = sample_item.workspace_id
        assert svc.delete(wid, "TestDomain") is True
        assert svc.delete(wid, "TestDomain") is False

    def test_export(self, test_session: Session, sample_item):
        data = ProjectService(test_session).export(sample_item.workspace_id, "TestDomain")
        assert data["project_data"]["project"]["name"] == "TestDomain"
        assert data["project_data"]["items"][0]["title"] == "Test Item"
