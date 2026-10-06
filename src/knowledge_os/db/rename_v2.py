"""Migração de dados do schema ANTIGO (domains/domain_id/project_links/project_key) pro
schema NOVO (projects/project_id/repo_links/repo_key — o estado atual de `db/models.py`).

À parte do `schema_sync.py`, que é puramente aditivo: aqui renomeamos tabelas, colunas e
índices de um banco já existente, criado antes desta branch.

Depois do rename, não é preciso chamar `schema_sync` aqui dentro: ele já roda normalmente
no startup do servidor (`main.py`) e cria `subjects`/`items.subject_id` sozinho (aditivos,
fora do escopo desta migração).

MySQL não é transacional em DDL: cada `ALTER`/`RENAME` roda na sua própria transação
(`engine.begin()` por operação), nunca numa transação só para tudo. Uma falha no meio pode
deixar o schema parcialmente migrado — o pré-voo de cada passo confere o estado atual antes
de agir (só renomeia `domains` se `domains` existir e `projects` não, por exemplo), então
rodar `rename_v2` de novo depois de uma falha parcial retoma do ponto certo sem duplicar
trabalho nem quebrar.
"""

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_OLD_TABLE = "domains"
_NEW_TABLE = "projects"
_OLD_LINK_TABLE = "project_links"
_NEW_LINK_TABLE = "repo_links"


def _table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _column_names(engine: Engine, table: str) -> set[str]:
    return {str(c["name"]) for c in inspect(engine).get_columns(table)}


def _index_names(engine: Engine, table: str) -> set[str]:
    return {str(i["name"]) for i in inspect(engine).get_indexes(table)}


def needs_migration(engine: Engine) -> bool:
    """True se o banco ainda tem a tabela do schema antigo (`domains`)."""
    return _OLD_TABLE in _table_names(engine)


def _rename_table(engine: Engine, db_type: str, old: str, new: str) -> None:
    if old not in _table_names(engine) or new in _table_names(engine):
        return
    with engine.begin() as conn:
        if db_type == "mysql":
            conn.execute(text(f"RENAME TABLE {old} TO {new}"))
        else:  # sqlite, postgresql
            conn.execute(text(f"ALTER TABLE {old} RENAME TO {new}"))


def _rename_column(
    engine: Engine,
    db_type: str,
    table: str,
    old: str,
    new: str,
    mysql_type: str,
    mysql_nullable: bool,
) -> None:
    cols = _column_names(engine, table)
    if old not in cols or new in cols:
        return
    with engine.begin() as conn:
        if db_type == "mysql":
            null_clause = "NULL" if mysql_nullable else "NOT NULL"
            conn.execute(
                text(f"ALTER TABLE {table} CHANGE COLUMN {old} {new} {mysql_type} {null_clause}")
            )
        else:  # sqlite, postgresql
            conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"))


def _rename_index(
    engine: Engine,
    db_type: str,
    table: str,
    old: str,
    new: str,
    columns: tuple[str, ...],
    unique: bool,
) -> None:
    existing = _index_names(engine, table)
    if new in existing:
        return
    if old not in existing:
        return
    with engine.begin() as conn:
        if db_type == "postgresql":
            conn.execute(text(f"ALTER INDEX {old} RENAME TO {new}"))
        else:  # sqlite, mysql: sem RENAME INDEX/ALTER INDEX — apaga e recria
            if db_type == "mysql":
                conn.execute(text(f"DROP INDEX {old} ON {table}"))
            else:
                conn.execute(text(f"DROP INDEX {old}"))
            unique_kw = "UNIQUE " if unique else ""
            cols = ", ".join(columns)
            conn.execute(text(f"CREATE {unique_kw}INDEX {new} ON {table} ({cols})"))


def rename_v2(engine: Engine) -> dict[str, Any]:
    """Migra um banco do schema antigo (domains/project_links) pro novo (projects/repo_links).

    Idempotente: se `domains` não existir (banco novo, ou já migrado), não faz nada e devolve
    `{"status": "nothing_to_do"}` — é o que torna seguro rodar este script mais de uma vez,
    inclusive depois de uma falha parcial (ver docstring do módulo).
    """
    if not needs_migration(engine):
        return {"status": "nothing_to_do"}

    warnings: list[str] = []
    backup_path: str | None = None

    from knowledge_os.services.maintenance import backup

    backed_up = backup("pre-rename-v2", engine)
    if backed_up is not None:
        backup_path = str(backed_up)
    else:
        warnings.append(
            "Backup automático só é feito para SQLite em arquivo; tire um snapshot externo "
            "do banco (pg_dump/mysqldump) antes de confirmar que esta migração rodou bem."
        )

    db_type = engine.dialect.name

    # Tabela domains -> projects primeiro (colunas de items/project_links referenciam o nome
    # novo depois).
    _rename_table(engine, db_type, _OLD_TABLE, _NEW_TABLE)

    _rename_column(
        engine,
        db_type,
        "items",
        "domain_id",
        "project_id",
        mysql_type="VARCHAR(36)",
        mysql_nullable=False,
    )

    _rename_table(engine, db_type, _OLD_LINK_TABLE, _NEW_LINK_TABLE)
    _rename_column(
        engine,
        db_type,
        _NEW_LINK_TABLE,
        "project_key",
        "repo_key",
        mysql_type="VARCHAR(512)",
        mysql_nullable=False,
    )
    _rename_column(
        engine,
        db_type,
        _NEW_LINK_TABLE,
        "domain_id",
        "project_id",
        mysql_type="VARCHAR(36)",
        mysql_nullable=False,
    )

    _rename_index(
        engine,
        db_type,
        _NEW_TABLE,
        "uq_domain_workspace_name",
        "uq_project_workspace_name",
        columns=("workspace_id", "name"),
        unique=True,
    )
    _rename_index(
        engine,
        db_type,
        _NEW_TABLE,
        "idx_domain_workspace",
        "idx_project_workspace",
        columns=("workspace_id",),
        unique=False,
    )
    _rename_index(
        engine,
        db_type,
        "items",
        "uq_item_domain_key",
        "uq_item_project_key",
        columns=("project_id", "item_key"),
        unique=True,
    )
    _rename_index(
        engine,
        db_type,
        _NEW_LINK_TABLE,
        "idx_project_link_domain",
        "idx_repo_link_project",
        columns=("project_id",),
        unique=False,
    )

    return {"status": "migrated", "backup_path": backup_path, "warnings": warnings}
