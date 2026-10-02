"""Modelos SQLAlchemy para Knowledge OS."""

from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Integer, DateTime, ForeignKey,
    UniqueConstraint, Index, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Workspace(Base):
    """Workspace: grande contexto."""
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    domains = relationship("Domain", back_populates="workspace", cascade="all, delete-orphan")
    items = relationship("Item", back_populates="workspace", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_workspace_name", "name"),
    )


class Domain(Base):
    """Domain: projeto/assunto dentro de um workspace."""
    __tablename__ = "domains"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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

    type = Column(String(50), nullable=False)  # context, rule, pattern, procedure, knowledge, insight, artifact
    memory_class = Column(String(50), nullable=False)  # ephemeral, working, longterm, canonical

    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    content = Column(Text, nullable=False)

    confidence = Column(Integer, nullable=True)  # 0-100
    importance = Column(Integer, nullable=True)  # 0-10

    ttl_days = Column(Integer, nullable=True)  # Para ephemeral

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    relation_type = Column(String(50), nullable=False)  # related_to, depends_on, implements, references, supersedes, derived_from
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_artifact_item", "item_id"),
    )
