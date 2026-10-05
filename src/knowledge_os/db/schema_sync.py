"""Sincroniza o schema de um banco com `Base.metadata`.

O aditivo é aplicado (tabelas, colunas, índices, FTS do dialect). O que não é aditivo
(tipo de coluna diferente) só é reportado em `pending_manual`.
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    bindparam,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.schema import CreateIndex

from knowledge_os.db.dialects import get_dialect
from knowledge_os.db.dialects.base import FTS_TABLE
from knowledge_os.db.models import Base
from knowledge_os.db.timeutil import utcnow
from knowledge_os.exceptions import DatabaseError

logger = logging.getLogger(__name__)

SCHEMA_META_TABLE = "schema_meta"
_VERSION_KEY = "schema_version"

# Fora de Base.metadata de propósito: é controle do sync, não modelo de domínio.
_meta = MetaData()
_schema_meta = Table(
    SCHEMA_META_TABLE,
    _meta,
    Column("key", String(50), primary_key=True),
    Column("value", String(255), nullable=False),
    Column("updated_at", DateTime, nullable=False),
)


def model_version() -> str:
    """Impressão digital do modelo atual (tabelas, colunas e tipos)."""
    parts = sorted(
        f"{t.name}.{c.name}:{c.type.__class__.__name__}"
        for t in Base.metadata.tables.values()
        for c in t.columns
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


def _affinity(type_: Any) -> Any:
    """Família do tipo. Boolean conta como Integer (o MySQL reflete BOOLEAN como TINYINT)."""
    affinity = type_._type_affinity
    return Integer if affinity is Boolean else affinity


def _literal_default(column: Column) -> str | None:
    """Default escalar do modelo como literal SQL; None se não houver."""
    default = column.default
    if default is None or not default.is_scalar:
        return None
    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _add_column(engine: Engine, table: Table, column: Column) -> None:
    preparer = engine.dialect.identifier_preparer
    sql = (
        f"ALTER TABLE {preparer.format_table(table)} ADD COLUMN "
        f"{preparer.format_column(column)} {column.type.compile(dialect=engine.dialect)}"
    )
    default = _literal_default(column)
    if default is not None:
        sql += f" DEFAULT {default}"
        if not column.nullable:
            sql += " NOT NULL"
    # Sem default, NOT NULL falharia em tabela com linhas: a coluna entra nullable.
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except OperationalError as exc:
        # Outro processo subindo junto adicionou a coluna primeiro: é o resultado desejado.
        if "duplicate column" not in str(exc).lower():
            raise
        if column.name not in {c["name"] for c in inspect(engine).get_columns(table.name)}:
            raise


def _create_index(engine: Engine, index: Index) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(CreateIndex(index))
    except OperationalError as exc:
        # Outro processo subindo junto criou o índice primeiro: é o resultado desejado.
        msg = str(exc).lower()
        if "already exists" not in msg and "duplicate key name" not in msg:  # SQLite/PG · MySQL
            raise


def _read_version(engine: Engine) -> str | None:
    if SCHEMA_META_TABLE not in inspect(engine).get_table_names():
        return None
    with engine.connect() as conn:
        return conn.execute(
            select(_schema_meta.c.value).where(_schema_meta.c.key == _VERSION_KEY)
        ).scalar()


def _write_version(engine: Engine, version: str) -> None:
    _meta.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(_schema_meta.delete().where(_schema_meta.c.key == _VERSION_KEY))
        conn.execute(
            _schema_meta.insert().values(
                key=_VERSION_KEY, value=version, updated_at=utcnow()
            )
        )


def _backfill_expires_at(engine: Engine) -> None:
    """Calcula expires_at dos ephemeral criados antes da coluna existir."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, created_at, ttl_days FROM items "
                "WHERE memory_class = 'ephemeral' AND ttl_days IS NOT NULL AND expires_at IS NULL"
            )
        ).all()
        for item_id, created_at, ttl_days in rows:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            expires = (created_at or utcnow()) + timedelta(days=int(ttl_days))
            conn.execute(
                text("UPDATE items SET expires_at = :e WHERE id = :i").bindparams(
                    bindparam("e", type_=DateTime)
                ),
                {"e": expires, "i": item_id},
            )


def _backup_before_changes(engine: Engine) -> None:
    """Cópia de segurança antes de alterar um banco que já tinha tabelas (SQLite em arquivo)."""
    from knowledge_os.services.maintenance import backup

    try:
        backup("pre-schema", engine)
    except Exception:  # noqa: BLE001 - sem backup não deve impedir a atualização
        logger.warning("Backup pre-schema falhou; seguindo com a atualização", exc_info=True)


def schema_sync(engine: Engine, dry_run: bool = False) -> dict[str, Any]:
    """Sincroniza o schema do banco com o modelo.

    Retorna `status` (created | updated | up_to_date | drift), `tables_created`,
    `columns_added` ("tabela.coluna"), `indexes_created` ("tabela.índice"), `fts_created`,
    `pending_manual`, `version` e `dry_run`. Com `dry_run=True` nada é gravado e as listas
    dizem o que seria aplicado.
    """
    try:
        return _sync(engine, dry_run)
    except SQLAlchemyError as exc:
        raise DatabaseError(f"Falha ao sincronizar o schema: {exc}") from exc


def _sync(engine: Engine, dry_run: bool) -> dict[str, Any]:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    model_tables = Base.metadata.tables

    tables_created = sorted(set(model_tables) - existing)
    columns_to_add: list[tuple[Table, Column]] = []
    indexes_to_create: list[Index] = []
    pending_manual: list[str] = []

    for name in sorted(set(model_tables) & existing):
        table = model_tables[name]
        reflected = {c["name"]: c["type"] for c in inspector.get_columns(name)}
        for column in table.columns:
            if column.name not in reflected:
                columns_to_add.append((table, column))
            elif _affinity(column.type) is not _affinity(reflected[column.name]):
                pending_manual.append(
                    f"{name}.{column.name}: tipo {reflected[column.name]} no banco, "
                    f"{column.type.compile(dialect=engine.dialect)} no modelo"
                )
        have = {i["name"] for i in inspector.get_indexes(name)}
        indexes_to_create += [
            i for i in sorted(table.indexes, key=lambda i: i.name or "") if i.name not in have
        ]

    dialect = get_dialect(engine.dialect.name)
    items_present = "items" in existing or "items" in tables_created
    # No SQLite a FTS é uma tabela virtual visível no inspect; nos demais dialects ela
    # nasce junto com a tabela items.
    if engine.dialect.name == "sqlite":
        fts_missing = items_present and FTS_TABLE not in existing
    else:
        fts_missing = "items" in tables_created
    fts_missing = fts_missing and dialect.supports_fts()
    version = model_version()

    has_changes = bool(tables_created or columns_to_add or indexes_to_create)
    if not dry_run:
        if has_changes and existing:
            _backup_before_changes(engine)
        if tables_created:
            Base.metadata.create_all(bind=engine, tables=[model_tables[t] for t in tables_created])
        for table, column in columns_to_add:
            _add_column(engine, table, column)
        if indexes_to_create:
            for index in indexes_to_create:
                _create_index(engine, index)
        if items_present and dialect.supports_fts():
            dialect.create_fts_table(engine)
        if "items.expires_at" in {f"{t.name}.{c.name}" for t, c in columns_to_add}:
            _backfill_expires_at(engine)
        if not pending_manual and _read_version(engine) != version:
            _write_version(engine, version)

    columns_added = [f"{t.name}.{c.name}" for t, c in columns_to_add]
    indexes_created = [f"{i.table.name}.{i.name}" for i in indexes_to_create]

    if pending_manual:
        status = "drift"
    elif tables_created:
        status = "created"
    elif columns_added or indexes_created or fts_missing:
        status = "updated"
    else:
        status = "up_to_date"

    return {
        "status": status,
        "tables_created": tables_created,
        "columns_added": columns_added,
        "indexes_created": indexes_created,
        "fts_created": fts_missing,
        "pending_manual": pending_manual,
        "version": version,
        "dry_run": dry_run,
    }
