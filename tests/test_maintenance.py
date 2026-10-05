"""Backup, manutenção diária e a corrida de schema entre dois processos."""

import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from knowledge_os import config
from knowledge_os.db.models import Artifact, Item, ItemTag, Tag
from knowledge_os.db.schema_sync import _add_column, schema_sync
from knowledge_os.db.session import create_db_engine, get_session
from knowledge_os.services import maintenance

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    engine = create_db_engine(f"sqlite:///{tmp_path / 'k.db'}")
    schema_sync(engine)
    yield engine
    engine.dispose()


def _item(s, ws, dm, key, memory_class="longterm", expires_at=None, *, type="knowledge",
          updated_at=None, access_count=0):
    item = Item(id=str(uuid.uuid4()), workspace_id=ws, domain_id=dm, key=key, type=type,
                memory_class=memory_class, title=key, summary="s", content="c",
                expires_at=expires_at, access_count=access_count)
    if updated_at:
        item.created_at = item.updated_at = updated_at
    s.add(item)
    return item


def _seed(engine):
    from knowledge_os.db.models import Domain, Workspace
    from knowledge_os.db.session import ensure_connection_row

    ensure_connection_row(engine)
    s = get_session(engine)
    ws, dm = Workspace(id="w", name="W", connection_id="default"), None
    s.add(ws)
    s.flush()
    dm = Domain(id="d", workspace_id="w", name="D")
    s.add(dm)
    s.commit()
    s.close()


def test_backup_abre_e_tem_os_itens(db):
    _seed(db)
    s = get_session(db)
    _item(s, "w", "d", "regra/a")
    s.commit()
    s.close()
    path = maintenance.backup("manual", db)
    assert path.parent == config.BACKUPS_DIR
    assert path.name.startswith("knowledge-") and path.name.endswith("-manual.db")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT item_key FROM items").fetchall() == [("regra/a",)]


def test_backup_rotaciona_mantendo_7_diarios(db):
    paths = [maintenance.backup("daily", db) for _ in range(9)]
    left = sorted(config.BACKUPS_DIR.glob("*-daily.db"))
    assert len(left) == 7 and left == sorted(paths)[-7:]


def test_backup_nao_faz_nada_fora_do_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    assert maintenance.backup("daily", create_engine("sqlite:///:memory:")) is None
    assert not (tmp_path / "backups").exists()


def test_run_daily_so_roda_uma_vez_por_dia(db, monkeypatch):
    monkeypatch.setattr("knowledge_os.db.session.get_engine", lambda *a: db)
    now = datetime(2026, 1, 10, 12)
    assert maintenance.run_daily(now)["ran"] is True
    assert maintenance.run_daily(now + timedelta(hours=3)) == {"ran": False}
    assert maintenance.run_daily(now + timedelta(days=1))["ran"] is True
    assert len(list(config.BACKUPS_DIR.glob("*-daily.db"))) == 2


def test_run_daily_apaga_ephemeral_com_ttl_vencido(db, monkeypatch):
    monkeypatch.setattr("knowledge_os.db.session.get_engine", lambda *a: db)
    _seed(db)
    now = datetime(2026, 1, 10, 12)
    s = get_session(db)
    velho = _item(s, "w", "d", "eph/velho", "ephemeral", now - timedelta(hours=1))
    _item(s, "w", "d", "eph/recente", "ephemeral", now + timedelta(days=1))
    _item(s, "w", "d", "regra/fixa", "longterm", now - timedelta(days=30), access_count=3)
    tag = Tag(id="t", name="t")
    s.add(tag)
    s.flush()
    s.add(ItemTag(item_id=velho.id, tag_id="t"))
    s.add(Artifact(id="a", item_id=velho.id, filename="f", file_path="p", mime_type="x/y",
                   file_size=1))
    s.commit()
    s.close()
    assert maintenance.run_daily(now)["expired"] == 1
    s = get_session(db)
    assert sorted(k for (k,) in s.execute(text("SELECT item_key FROM items"))) == [
        "eph/recente", "regra/fixa"]
    assert s.execute(text("SELECT count(*) FROM item_tags")).scalar() == 0
    s.close()


def test_schema_sync_com_mudanca_cria_backup_pre_schema(db):
    with db.begin() as conn:
        conn.execute(text("ALTER TABLE domains DROP COLUMN description"))
    assert schema_sync(db)["columns_added"] == ["domains.description"]
    assert len(list(config.BACKUPS_DIR.glob("*-pre-schema.db"))) == 1
    schema_sync(db)  # sem mudança: sem novo backup
    assert len(list(config.BACKUPS_DIR.glob("*-pre-schema.db"))) == 1


def test_add_column_tolera_coluna_que_outro_processo_criou(db):
    table = Item.__table__
    with db.begin() as conn:
        conn.execute(text("ALTER TABLE domains DROP COLUMN description"))
    from knowledge_os.db.models import Domain

    col = Domain.__table__.c.description
    _add_column(db, Domain.__table__, col)
    _add_column(db, Domain.__table__, col)  # "duplicate column": é sucesso
    assert "description" in {c["name"] for c in inspect(db).get_columns("domains")}
    assert table is not None


def test_dois_processos_subindo_juntos_com_coluna_nova(tmp_path):
    db_path = tmp_path / "k.db"
    seed = create_db_engine(f"sqlite:///{db_path}")
    schema_sync(seed)
    with seed.begin() as conn:
        conn.execute(text("DROP INDEX idx_item_expires"))
        conn.execute(text("ALTER TABLE items DROP COLUMN expires_at"))
    seed.dispose()
    go = tmp_path / "go"
    code = (
        "import sys, time, pathlib\n"
        "from knowledge_os.db.session import create_db_engine\n"
        "from knowledge_os.db.schema_sync import schema_sync\n"
        "e = create_db_engine(sys.argv[1])\n"
        "while not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.001)\n"
        "print(schema_sync(e)['status'])\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
           "KNOWLEDGE_OS_HOME": str(tmp_path / "home")}
    procs = [subprocess.Popen([sys.executable, "-c", code, f"sqlite:///{db_path}", str(go)],
                              env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) for _ in range(2)]
    time.sleep(3)  # ambos importados e esperando a largada
    go.write_text("go")
    outs = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    check = create_db_engine(f"sqlite:///{db_path}")
    assert "expires_at" in {c["name"] for c in inspect(check).get_columns("items")}
    check.dispose()


class _BackupQuebrado:
    """Conexão de origem cujo backup morre no meio (servidor morto)."""

    def __init__(self, conn):
        self._conn = conn

    def backup(self, target):
        raise RuntimeError("morreu no meio")

    def close(self):
        self._conn.close()


def _backup_que_morre(monkeypatch):
    import types

    real = sqlite3.connect
    first = []

    def fake(path, *a, **kw):
        conn = real(path, *a, **kw)
        if not first:
            first.append(1)
            return _BackupQuebrado(conn)
        return conn

    monkeypatch.setattr(maintenance, "sqlite3", types.SimpleNamespace(connect=fake))


def test_backup_interrompido_nao_deixa_arquivo_com_nome_final(db, monkeypatch):
    _backup_que_morre(monkeypatch)
    with pytest.raises(RuntimeError):
        maintenance.backup("daily", db)
    assert list(config.BACKUPS_DIR.glob("knowledge-*.db")) == []
    assert list(config.BACKUPS_DIR.glob("*.tmp")) == []


def test_run_daily_que_falha_nao_marca_o_dia(db, monkeypatch):
    monkeypatch.setattr("knowledge_os.db.session.get_engine", lambda *a: db)
    monkeypatch.setattr(config, "KNOWLEDGE_HOME", config.BACKUPS_DIR.parent)
    _backup_que_morre(monkeypatch)
    now = datetime(2026, 1, 10, 12)
    with pytest.raises(RuntimeError):
        maintenance.run_daily(now)
    assert not (config.KNOWLEDGE_HOME / maintenance.MARKER_NAME).exists()
    assert maintenance.run_daily(now)["ran"] is True


def test_run_daily_deixa_o_wal_com_zero_bytes(db, monkeypatch):
    monkeypatch.setattr("knowledge_os.db.session.get_engine", lambda *a: db)
    _seed(db)
    s = get_session(db)
    _item(s, "w", "d", "regra/a")
    s.commit()
    s.close()
    wal = Path(str(db.url.database) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0
    maintenance.run_daily(datetime(2026, 1, 10, 12))
    assert not wal.exists() or wal.stat().st_size == 0


def test_memoria_de_longa_duracao_nunca_expira_sozinha(db, monkeypatch):
    """Só o temporário (ephemeral com TTL) é apagado; aprendizado nunca usado continua."""
    monkeypatch.setattr("knowledge_os.db.session.get_engine", lambda *a: db)
    _seed(db)
    now = datetime(2027, 6, 10, 12)
    s = get_session(db)
    for key, type_ in (("gotcha/nunca", "knowledge"), ("regra/nunca", "rule"),
                       ("decisao/nunca", "insight"), ("mudanca/x", "task")):
        _item(s, "w", "d", key, type=type_, updated_at=now - timedelta(days=400))
    s.commit()
    s.close()
    assert maintenance.run_daily(now)["expired"] == 0
    s = get_session(db)
    assert s.execute(text("SELECT count(*) FROM items")).scalar() == 4
    s.close()
