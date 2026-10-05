"""Modelos SQLAlchemy para Knowledge OS."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

from knowledge_os.db.timeutil import utcnow

Base = declarative_base()

# Connection "default": o próprio banco do catálogo (knowledge.db). Workspaces criados
# sem connection_id (T1-T5) pertencem a ela.
DEFAULT_CONNECTION_ID = "default"
DEFAULT_CONNECTION_NAME = "default"


class Connection(Base):
    """Connection: ponto de acesso a um banco de dados (SQLite, MySQL ou PostgreSQL)."""
    __tablename__ = "connections"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    db_type = Column(String(20), nullable=False)  # sqlite, mysql, postgresql
    db_url = Column(String(2048), nullable=False)
    host = Column(String(255), nullable=True)
    port = Column(Integer, nullable=True)
    database = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    last_tested = Column(DateTime, nullable=True)
    test_result = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    workspaces = relationship(
        "Workspace", back_populates="connection", cascade="all, delete-orphan"
    )


class Workspace(Base):
    """Workspace: grande contexto."""
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True)
    connection_id = Column(
        String(36), ForeignKey("connections.id"), nullable=False, default=DEFAULT_CONNECTION_ID
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    connection = relationship("Connection", back_populates="workspaces")
    domains = relationship("Domain", back_populates="workspace", cascade="all, delete-orphan")
    items = relationship("Item", back_populates="workspace", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("connection_id", "name", name="uq_workspace_connection_name"),
        Index("idx_workspace_connection", "connection_id"),
        Index("idx_workspace_name", "name"),
    )


class Domain(Base):
    """Domain: projeto/assunto dentro de um workspace."""
    __tablename__ = "domains"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    workspace = relationship("Workspace", back_populates="domains")
    items = relationship("Item", back_populates="domain", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_domain_workspace_name"),
        Index("idx_domain_workspace", "workspace_id"),
    )


class Item(Base):
    """Item: unidade de conhecimento."""
    __tablename__ = "items"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    domain_id = Column(String(36), ForeignKey("domains.id"), nullable=False)

    # context, rule, pattern, procedure, knowledge, insight, artifact
    type = Column(String(50), nullable=False)
    memory_class = Column(String(50), nullable=False)  # ephemeral, working, longterm, canonical

    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    content = Column(Text, nullable=False)

    confidence = Column(Integer, nullable=True)  # 0-100
    importance = Column(Integer, nullable=True)  # 0-10

    ttl_days = Column(Integer, nullable=True)  # Para ephemeral
    expires_at = Column(DateTime, nullable=True)  # ephemeral: created/renewed + ttl_days

    # Segundo cérebro (Plumb): chave estável por domain, para upsert sem duplicar.
    # Coluna "item_key": `key` é palavra reservada no MySQL e a busca usa SQL textual.
    key = Column("item_key", String(200), nullable=True)
    keywords = Column(Text, nullable=True)  # sinônimos e termos de busca extras
    source = Column(String(500), nullable=True)  # origem: mudança, commit, sessão
    status = Column(String(20), nullable=False, default="active")  # active|superseded|deprecated
    scope_paths = Column(Text, nullable=True)  # JSON: globs onde a regra vale

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    last_accessed = Column(DateTime, nullable=True)
    access_count = Column(Integer, default=0)

    # Relacionamentos
    workspace = relationship("Workspace", back_populates="items")
    domain = relationship("Domain", back_populates="items")
    tags = relationship("Tag", secondary="item_tags", back_populates="items")
    labels = relationship("Label", secondary="item_labels", back_populates="items")

    __table_args__ = (
        Index("idx_item_workspace", "workspace_id"),
        Index("idx_item_domain", "domain_id"),
        Index("idx_item_type", "type"),
        Index("idx_item_memory", "memory_class"),
        Index("idx_item_created", "created_at"),
        Index("idx_item_updated", "updated_at"),
        Index("idx_item_status", "status"),
        Index("idx_item_expires", "expires_at"),
        Index("uq_item_domain_key", "domain_id", "item_key", unique=True),
    )


class Tag(Base):
    """Tag: etiqueta reutilizável."""
    __tablename__ = "tags"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), unique=True, nullable=False)

    items = relationship("Item", secondary="item_tags", back_populates="tags")


class ItemTag(Base):
    """Relação muitos-para-muitos: Item <-> Tag."""
    __tablename__ = "item_tags"

    item_id = Column(String(36), ForeignKey("items.id"), primary_key=True)
    tag_id = Column(String(36), ForeignKey("tags.id"), primary_key=True)


class Label(Base):
    """Label: etiqueta controlada (official, critical, experimental, deprecated, reference)."""
    __tablename__ = "labels"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), unique=True, nullable=False)

    items = relationship("Item", secondary="item_labels", back_populates="labels")


class ItemLabel(Base):
    """Relação muitos-para-muitos: Item <-> Label."""
    __tablename__ = "item_labels"

    item_id = Column(String(36), ForeignKey("items.id"), primary_key=True)
    label_id = Column(String(36), ForeignKey("labels.id"), primary_key=True)


class Relation(Base):
    """Relação semântica entre items."""
    __tablename__ = "relations"

    id = Column(String(36), primary_key=True)
    source_item_id = Column(String(36), ForeignKey("items.id"), nullable=False)
    target_item_id = Column(String(36), ForeignKey("items.id"), nullable=False)
    # related_to, depends_on, implements, references, supersedes, derived_from
    relation_type = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_relation_source", "source_item_id"),
        Index("idx_relation_target", "target_item_id"),
        Index("idx_relation_type", "relation_type"),
    )


class Artifact(Base):
    """Artifact: arquivo anexado a um item."""
    __tablename__ = "artifacts"

    id = Column(String(36), primary_key=True)
    item_id = Column(String(36), ForeignKey("items.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(1024), nullable=False)  # Relativo a ARTIFACTS_DIR
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_artifact_item", "item_id"),
    )


class ProjectLink(Base):
    """Liga um projeto (remote do git ou caminho normalizado) a um workspace/domain."""
    __tablename__ = "project_links"

    project_key = Column(String(512), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    domain_id = Column(String(36), ForeignKey("domains.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("idx_project_link_domain", "domain_id"),)
