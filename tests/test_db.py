"""Testes para modelos de banco de dados."""

from sqlalchemy.orm import Session

from knowledge_os.db.models import Domain, Item, Workspace


class TestWorkspace:
    """Testes para modelo Workspace."""

    def test_criar_workspace(self, test_session: Session):
        """Testa criação de workspace."""
        ws = Workspace(id="ws_1", name="Test", description="Test workspace")
        test_session.add(ws)
        test_session.commit()

        assert ws.id == "ws_1"
        assert ws.name == "Test"
        # TODO: Implementar mais assertions

    def test_criar_domain(self, test_session: Session, sample_workspace: Workspace):
        """Testa criação de domain com workspace."""
        dm = Domain(
            id="dm_1",
            workspace_id=sample_workspace.id,
            name="TestDomain"
        )
        test_session.add(dm)
        test_session.commit()

        assert dm.workspace_id == sample_workspace.id
        # TODO: Implementar mais assertions


class TestItem:
    """Testes para modelo Item."""

    def test_criar_item(
        self, test_session: Session, sample_workspace: Workspace, sample_domain: Domain
    ):
        """Testa criação de item."""
        item = Item(
            id="it_1",
            workspace_id=sample_workspace.id,
            domain_id=sample_domain.id,
            type="knowledge",
            memory_class="longterm",
            title="Test",
            summary="Test summary",
            content="Test content"
        )
        test_session.add(item)
        test_session.commit()

        assert item.type == "knowledge"
        # TODO: Implementar mais assertions

    def test_fts_index(self, test_session: Session, sample_item: Item):
        """Testa FTS5 indexing e busca."""
        from sqlalchemy import text

        # Busca por palavra-chave no FTS5
        result = test_session.execute(
            text("""
                SELECT rowid FROM items_fts
                WHERE items_fts MATCH 'Spring'
            """)
        ).scalar()

        assert result is not None
        # TODO: Implementar mais assertions


class TestRelations:
    """Testes para relações entre items."""
    # TODO: Implementar


class TestTags:
    """Testes para tags e labels."""
    # TODO: Implementar
