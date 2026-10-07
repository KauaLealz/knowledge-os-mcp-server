"""Testes da migração de dados do schema antigo (domains/project_links) pro novo
(projects/repo_links). O schema antigo não existe mais no código (já virou o novo), então
é construído aqui via SQL puro, como fixture."""

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from knowledge_os.db.rename_v2 import rename_v2
from knowledge_os.db.session import create_db_engine


def _old_schema_engine(tmp_path: Path):
    return _write_old_schema(tmp_path / "old.db")


def _write_old_schema(db_path: Path):
    engine = create_db_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
                "description TEXT, created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE domains (id VARCHAR(36) PRIMARY KEY, "
                "workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id), "
                "name VARCHAR(255) NOT NULL, description TEXT, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text("CREATE UNIQUE INDEX uq_domain_workspace_name ON domains (workspace_id, name)")
        )
        conn.execute(text("CREATE INDEX idx_domain_workspace ON domains (workspace_id)"))
        conn.execute(
            text(
                "CREATE TABLE items (id VARCHAR(36) PRIMARY KEY, "
                "workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id), "
                "domain_id VARCHAR(36) NOT NULL REFERENCES domains(id), "
                "type VARCHAR(50) NOT NULL, memory_class VARCHAR(50) NOT NULL, "
                "title VARCHAR(255) NOT NULL, summary TEXT NOT NULL, content TEXT NOT NULL, "
                "item_key VARCHAR(200), status VARCHAR(20) NOT NULL DEFAULT 'active', "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX uq_item_domain_key ON items (domain_id, item_key)"))
        conn.execute(text("CREATE INDEX idx_item_domain ON items (domain_id)"))
        conn.execute(
            text(
                "CREATE TABLE project_links (project_key VARCHAR(512) PRIMARY KEY, "
                "workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id), "
                "domain_id VARCHAR(36) NOT NULL REFERENCES domains(id), "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(text("CREATE INDEX idx_project_link_domain ON project_links (domain_id)"))
        conn.execute(text("INSERT INTO workspaces (id, name) VALUES ('w1', 'Workspace 1')"))
        conn.execute(
            text("INSERT INTO domains (id, workspace_id, name) VALUES ('d1', 'w1', 'Domain 1')")
        )
        conn.execute(
            text(
                "INSERT INTO items (id, workspace_id, domain_id, type, memory_class, title, "
                "summary, content, item_key) VALUES "
                "('i1', 'w1', 'd1', 'context', 'longterm', 'Title', 'Summary', 'Content', 'k1')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO project_links (project_key, workspace_id, domain_id) "
                "VALUES ('github.com/foo/bar', 'w1', 'd1')"
            )
        )
    return engine


def test_rename_v2_migra_schema_antigo_para_novo(tmp_path):
    engine = _old_schema_engine(tmp_path)

    result = rename_v2(engine)

    assert result["status"] == "migrated"

    tables = set(inspect(engine).get_table_names())
    assert "projects" in tables
    assert "domains" not in tables
    assert "repo_links" in tables
    assert "project_links" not in tables

    item_cols = {c["name"] for c in inspect(engine).get_columns("items")}
    assert "project_id" in item_cols
    assert "domain_id" not in item_cols

    repo_cols = {c["name"] for c in inspect(engine).get_columns("repo_links")}
    assert "repo_key" in repo_cols
    assert "project_id" in repo_cols
    assert "project_key" not in repo_cols
    assert "domain_id" not in repo_cols

    with engine.connect() as conn:
        item_row = conn.execute(text("SELECT project_id FROM items WHERE id = 'i1'")).one()
        assert item_row.project_id == "d1"

        link_row = conn.execute(
            text(
                "SELECT repo_key, project_id FROM repo_links WHERE repo_key = 'github.com/foo/bar'"
            )
        ).one()
        assert link_row.project_id == "d1"

    project_indexes = {i["name"] for i in inspect(engine).get_indexes("projects")}
    assert "uq_project_workspace_name" in project_indexes
    assert "idx_project_workspace" in project_indexes

    item_indexes = {i["name"] for i in inspect(engine).get_indexes("items")}
    assert "uq_item_project_key" in item_indexes
    assert "idx_item_project" in item_indexes
    assert "idx_item_domain" not in item_indexes

    repo_link_indexes = {i["name"] for i in inspect(engine).get_indexes("repo_links")}
    assert "idx_repo_link_project" in repo_link_indexes


def test_rename_v2_e_idempotente(tmp_path):
    engine = _old_schema_engine(tmp_path)

    rename_v2(engine)
    result = rename_v2(engine)

    assert result == {"status": "nothing_to_do"}


def test_rename_v2_banco_ja_novo_nao_faz_nada(tmp_path):
    """Banco criado direto no schema novo (sem `domains`): pré-voo não mexe em nada."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'new.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, "
                "workspace_id VARCHAR(36) NOT NULL, name VARCHAR(255) NOT NULL)"
            )
        )

    result = rename_v2(engine)

    assert result == {"status": "nothing_to_do"}
    assert "projects" in set(inspect(engine).get_table_names())


def test_cli_migrate_v2_migra_de_verdade_sem_rodar_schema_sync_antes(tmp_path):
    """Regressão: `knowledge-mcp --migrate-v2` tem que migrar os dados de verdade.

    `get_engine()`/`init_db()` rodam `schema_sync` (aditivo) assim que são chamados — isso
    criaria `projects`/`repo_links` vazias ANTES do `rename_v2` rodar, fazendo o pré-voo achar
    que já estava tudo migrado (tabela nova já existe) e pular o rename de verdade, perdendo os
    dados presos nas tabelas antigas. O CLI precisa usar um engine cru (sem passar por
    `get_engine()`) para o `rename_v2` ver o schema antigo de fato.
    """
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "indexes" / "default.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _write_old_schema(db_path)

    env = {**os.environ, "KNOWLEDGE_OS_HOME": str(home)}
    out = subprocess.run(
        [sys.executable, "-m", "knowledge_os.main", "--migrate-v2"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["status"] == "migrated", result

    # Confere no arquivo de verdade, sem reaproveitar nenhum engine do processo do CLI.
    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert "projects" in tables
    assert "domains" not in tables

    with engine.connect() as conn:
        item_row = conn.execute(text("SELECT project_id FROM items WHERE id = 'i1'")).one()
        assert item_row.project_id == "d1"  # o dado migrado de verdade, não uma tabela vazia
    engine.dispose()


def test_rename_v2_depois_schema_sync_nao_duplica_indice_de_items(tmp_path):
    """Regressão: faltava renomear `idx_item_domain`, então o `schema_sync` do startup normal
    (que só cria índice por nome, nunca reconhece um já renomeado) criava um `idx_item_project`
    novo do zero ao lado do `idx_item_domain` órfão — dois índices na mesma coluna."""
    from knowledge_os.db.schema_sync import schema_sync

    engine = _old_schema_engine(tmp_path)
    rename_v2(engine)
    schema_sync(engine)

    item_indexes = {i["name"] for i in inspect(engine).get_indexes("items")}
    assert "idx_item_domain" not in item_indexes
    assert "idx_item_project" in item_indexes
    assert sum(1 for i in inspect(engine).get_indexes("items")
               if i["column_names"] == ["project_id"] and not i["unique"]) == 1
