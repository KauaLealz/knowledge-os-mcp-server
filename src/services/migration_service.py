"""Migração de dados entre bancos (ex.: SQLite local -> PostgreSQL)."""

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import Connection as Connection_
from sqlalchemy import Engine, MetaData, Table, create_engine, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import ARTIFACTS_DIR
from src.db.dialects import detect_type, normalize_url, redact
from src.db.models import DEFAULT_CONNECTION_ID, DEFAULT_CONNECTION_NAME, Base
from src.db.session import create_db_engine, init_db, redact_url
from src.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

CHUNK = 500
# Ordem de cópia: respeita as FKs.
TABLES = (
    "workspaces", "domains", "tags", "labels", "items",
    "item_tags", "item_labels", "relations", "artifacts",
)
# Tabelas cujo registro é identificado pelo nome: se já existe no destino, reaproveita.
MERGE_BY_NAME = {"tags": "item_tags", "labels": "item_labels"}
MERGE_FK = {"item_tags": ("tag_id", "tags"), "item_labels": ("label_id", "labels")}


class MigrationService:
    """Copia workspaces, domains, items, tags, labels, relations e artifacts entre bancos."""

    def migrate_sqlite_to_postgresql(
        self,
        sqlite_path: str,
        postgresql_url: str,
        connection_id: str | None = None,
        connection_name: str | None = None,
    ) -> dict[str, Any]:
        """Migra os dados de um arquivo SQLite para um PostgreSQL.

        Retorna {workspaces, domains, items, artifacts, relations, tags, labels,
        errors, warnings}. A migração é atômica: se algo falha, nada é gravado no
        destino e `errors` explica o motivo.
        """
        path = Path(sqlite_path)
        if not path.is_file():
            raise NotFoundError(f"Arquivo SQLite não encontrado: {sqlite_path}")
        if detect_type(postgresql_url) != "postgresql":
            raise ValidationError("O destino deve ser uma URL postgresql")
        return self.migrate(
            f"sqlite:///{path.resolve().as_posix()}",
            normalize_url(postgresql_url),
            connection_id=connection_id,
            connection_name=connection_name,
        )

    def migrate(
        self,
        source_url: str,
        target_url: str,
        connection_id: str | None = None,
        connection_name: str | None = None,
    ) -> dict[str, Any]:
        """Migra entre quaisquer dois bancos suportados.

        `connection_id` (e `connection_name`) reetiquetam os workspaces migrados para
        uma connection do destino; sem eles cada workspace mantém a sua (ou "default").
        """
        result: dict[str, Any] = {t: 0 for t in TABLES}
        result.update(errors=[], warnings=[])
        # Origem só é lida; engine simples evita alterar o arquivo (sem PRAGMAs/WAL).
        source = create_engine(normalize_url(source_url))
        target: Engine | None = None
        try:
            target = create_db_engine(normalize_url(target_url))
            init_db(
                target,
                connection_id=connection_id or DEFAULT_CONNECTION_ID,
                connection_name=(connection_name or connection_id or DEFAULT_CONNECTION_NAME),
            )
            counts = self._copy_all(source, target, connection_id, connection_name, result)
            result.update(counts)
        except (SQLAlchemyError, ValidationError, NotFoundError) as exc:
            logger.error("Migração falhou: %s", exc)
            message = redact(redact(str(exc), target_url), source_url)
            result["errors"].append(message)
            for table in TABLES:
                result[table] = 0
        finally:
            source.dispose()
            if target is not None:
                target.dispose()
        return result

    # ------------------------------------------------------------------ internos

    def _copy_all(
        self,
        source: Engine,
        target: Engine,
        connection_id: str | None,
        connection_name: str | None,
        result: dict[str, Any],
    ) -> dict[str, int]:
        available = set(inspect(source).get_table_names())
        source_meta = MetaData()
        copied: dict[str, int] = {}
        expected: dict[str, int] = {}
        id_map: dict[str, dict[str, str]] = {"tags": {}, "labels": {}}
        connection_names = self._source_connection_names(source, available)

        with source.connect() as sconn, target.begin() as tconn:
            for name in TABLES:
                copied[name] = 0
                expected[name] = 0
                if name not in available:
                    continue
                src_table = Table(name, source_meta, autoload_with=source)
                dst_table: Table = Base.metadata.tables[name]
                columns = {c.name for c in dst_table.columns}
                before = tconn.scalar(select(func.count()).select_from(dst_table)) or 0
                existing: dict[str, str] = {}
                if name in MERGE_BY_NAME:
                    rows = tconn.execute(select(dst_table.c.name, dst_table.c.id))
                    existing = {r.name: r.id for r in rows}
                stream = sconn.execution_options(stream_results=True).execute(src_table.select())
                for partition in stream.partitions(CHUNK):
                    batch: list[dict[str, Any]] = []
                    for row in partition:
                        data = {k: v for k, v in row._mapping.items() if k in columns}
                        expected[name] += 1
                        if name in MERGE_BY_NAME and data["name"] in existing:
                            id_map[name][data["id"]] = existing[data["name"]]
                            continue
                        if name in MERGE_FK:
                            column, ref = MERGE_FK[name]
                            data[column] = id_map[ref].get(data[column], data[column])
                        if name == "workspaces":
                            data["connection_id"] = (
                                connection_id or data.get("connection_id") or DEFAULT_CONNECTION_ID
                            )
                            self._ensure_workspace_connection(
                                tconn, target, data["connection_id"], connection_name,
                                connection_names,
                            )
                        if name == "artifacts":
                            self._check_artifact_file(data, result["warnings"])
                        batch.append(data)
                    if batch:
                        tconn.execute(dst_table.insert(), batch)
                        copied[name] += len(batch)
                after = tconn.scalar(select(func.count()).select_from(dst_table)) or 0
                merged = expected[name] - copied[name]
                if after - before != copied[name] or (merged and name not in MERGE_BY_NAME):
                    raise ValidationError(
                        f"Contagem divergente em {name}: origem={expected[name]}, "
                        f"gravados={after - before}"
                    )
        return copied

    @staticmethod
    def _source_connection_names(source: Engine, available: set[str]) -> dict[str, str]:
        if "connections" not in available:
            return {}
        table = Table("connections", MetaData(), autoload_with=source)
        with source.connect() as conn:
            return {r.id: r.name for r in conn.execute(select(table.c.id, table.c.name))}

    @staticmethod
    def _ensure_workspace_connection(
        tconn: Connection_,
        target: Engine,
        cid: str,
        forced_name: str | None,
        names: dict[str, str],
    ) -> None:
        """Garante, na mesma transação, a linha de connections exigida pela FK."""
        table: Table = Base.metadata.tables["connections"]
        if tconn.scalar(select(table.c.id).where(table.c.id == cid)) is not None:
            return
        tconn.execute(
            table.insert().values(
                id=cid,
                name=forced_name or names.get(cid) or cid,
                db_type=target.dialect.name,
                db_url=redact_url(target.url.render_as_string(hide_password=True)),
                is_active=True,
            )
        )

    @staticmethod
    def _check_artifact_file(row: dict[str, Any], warnings: list[str]) -> None:
        """Os bytes ficam em ARTIFACTS_DIR (compartilhado); só confere se o arquivo existe."""
        if not (ARTIFACTS_DIR / str(row.get("file_path", ""))).is_file():
            warnings.append(f"Arquivo do artifact não encontrado em disco: {row.get('file_path')}")

