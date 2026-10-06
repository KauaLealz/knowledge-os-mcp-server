"""Testes do SubjectService: agrupador opcional de items dentro de um project."""

import pytest
from sqlalchemy.orm import Session

from knowledge_os.db.models import Item, Project
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.subject_service import SubjectService


class TestSubjectService:
    def test_create_get_list(self, test_session: Session, sample_project: Project):
        svc = SubjectService(test_session)
        sj = svc.create(sample_project.id, "backend", "assuntos de backend")
        assert sj.id and sj.name == "backend" and sj.description == "assuntos de backend"
        assert svc.get(sample_project.id, "backend").id == sj.id
        assert [x.name for x in svc.list(sample_project.id)] == ["backend"]

    def test_list_ordenada_por_criacao(self, test_session: Session, sample_project: Project):
        svc = SubjectService(test_session)
        svc.create(sample_project.id, "s1", None)
        svc.create(sample_project.id, "s2", None)
        assert [x.name for x in svc.list(sample_project.id)] == ["s1", "s2"]

    def test_create_project_inexistente(self, test_session: Session):
        with pytest.raises(NotFoundError):
            SubjectService(test_session).create("project-que-nao-existe", "s1", None)

    def test_unicidade_por_project_e_nome(self, test_session: Session, sample_project: Project):
        svc = SubjectService(test_session)
        svc.create(sample_project.id, "s1", None)
        with pytest.raises(ValidationError):
            svc.create(sample_project.id, "s1", None)

    def test_mesmo_nome_em_projects_diferentes_nao_colide(
        self, test_session: Session, sample_project: Project
    ):
        from knowledge_os.services.project_service import ProjectService

        outro = ProjectService(test_session).create(sample_project.workspace_id, "outro-project")
        svc = SubjectService(test_session)
        svc.create(sample_project.id, "s1", None)
        # Não levanta: é outro project.
        sj2 = svc.create(outro.id, "s1", None)
        assert sj2.project_id == outro.id

    def test_get_inexistente(self, test_session: Session, sample_project: Project):
        with pytest.raises(NotFoundError):
            SubjectService(test_session).get(sample_project.id, "nada")

    def test_delete_inexistente_retorna_false(
        self, test_session: Session, sample_project: Project
    ):
        assert SubjectService(test_session).delete(sample_project.id, "nada") is False

    def test_delete_desvincula_items_em_vez_de_apagar(
        self, test_session: Session, sample_item: Item
    ):
        svc = SubjectService(test_session)
        sj = svc.create(sample_item.project_id, "s1", None)
        sample_item.subject_id = sj.id
        test_session.commit()
        item_id = sample_item.id

        assert svc.delete(sample_item.project_id, "s1") is True
        assert svc.delete(sample_item.project_id, "s1") is False

        item = test_session.get(Item, item_id)
        assert item is not None  # o item continua existindo
        assert item.subject_id is None  # só desvinculado
