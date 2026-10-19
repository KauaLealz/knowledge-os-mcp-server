"""Migração única v2 → v6 na pasta de uma conexão (knowledge-mcp migrate)."""

from knowledge_os.services.item_file import parse_item_file
from knowledge_os.services.migrate import migrate_connection, migrate_item_text, migrate_meta_text

V2_RULE = """---
key: rule/money
id: aaaaaaaa-0000-0000-0000-000000000001
workspace: W
project: P
type: rule
title: Money em pagamentos
subtype: security
scope: workspace
status: review
tags:
  - pix
links:
  - title: Painel
    url: https://painel.exemplo.com
scope_paths:
  - src/payments/**
keywords: pagamento
origin: user
created_at: '2026-01-01T00:00:00Z'
updated_at: '2026-01-02T00:00:00Z'
relations:
  - type: supersedes
    target: rule/old
summary: Valores em centavos
---
corpo da regra
"""

V2_SPEC = """---
key: spec/pay-1
id: aaaaaaaa-0000-0000-0000-000000000002
workspace: W
project: P
type: spec
title: Pix
subtype: change
status: done
tags: []
created_at: '2026-01-01T00:00:00Z'
updated_at: '2026-01-02T00:00:00Z'
summary: Uma mudanca
---
plano
"""

V2_META = """name: Workspace
scope: global
subjects:
  - name: Credito
    scope: workspace
  - name: Titulo
"""


def test_migrate_item_rule_para_v6(conn):
    out = parse_item_file(migrate_item_text(V2_RULE))
    assert out["type"] == "rule"
    assert "security" in out["tags"] and "archived" in out["tags"] and "pix" in out["tags"]
    assert {"url": "https://painel.exemplo.com", "title": "Painel"} in out["links"]
    assert {"path": "src/payments/**"} in out["links"]
    assert {"item": "rule/old", "rel": "relates_to"} in out["links"]  # supersedes -> relates_to


def test_migrate_spec_vira_work(conn):
    out = parse_item_file(migrate_item_text(V2_SPEC))
    assert out["type"] == "work"
    assert "done" in out["tags"]  # status do work vira tag de ciclo


def test_migrate_meta_tira_scope(conn):
    new = migrate_meta_text(V2_META)
    assert "scope:" not in new
    assert "Credito" in new and "Titulo" in new


def test_migrate_e_idempotente(conn):
    once = migrate_item_text(V2_RULE)
    assert migrate_item_text(once) is None  # ja em v6, nao mexe


def test_migrate_connection_reescreve_a_pasta(conn, data_dir):
    (data_dir / "w" / "p").mkdir(parents=True)
    (data_dir / "w" / "p" / "rule" / "money.md").parent.mkdir(parents=True)
    (data_dir / "w" / "p" / "rule" / "money.md").write_text(V2_RULE, encoding="utf-8")
    (data_dir / "w" / ".knowledge.yaml").write_text(V2_META, encoding="utf-8")

    res = migrate_connection(conn.id)
    assert res["migrated"] == 2
    # Agora os arquivos passam no parser do v6.
    txt = (data_dir / "w" / "p" / "rule" / "money.md").read_text(encoding="utf-8")
    assert parse_item_file(txt)["type"] == "rule"
    assert "scope" not in (data_dir / "w" / ".knowledge.yaml").read_text(encoding="utf-8")
    # Segunda passada: nada a migrar.
    assert migrate_connection(conn.id)["migrated"] == 0
