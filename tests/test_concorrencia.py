"""Vários processos no mesmo SQLite: retentativa nas escritas e _track best-effort."""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from knowledge_os.db import session as session_mod
from knowledge_os.db.session import create_db_engine, init_db
from knowledge_os.exceptions import DatabaseError
from knowledge_os.services.context_service import ContextService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.project_service import ProjectService

ROOT = Path(__file__).resolve().parent.parent

WORKER = (
    "import sys\n"
    "from knowledge_os.config import ensure_home, validate_and_init_config\n"
    "ensure_home(); validate_and_init_config()\n"
    "from knowledge_os.config import ConfigManager\n"
    "ConfigManager.load_or_create()  # o preparo cria o connections.json antes da disputa\n"
    "from knowledge_os.services.item_service import ItemService\n"
    "n = int(sys.argv[2])\n"
    "svc = ItemService()\n"
    "for i in range(25):\n"
    "    svc.save([{'workspace': 'W', 'domain': 'D', 'key': f'p{n}/{i}', 'type': 'knowledge',\n"
    "               'memory_class': 'working', 'title': f't{n}-{i}', 'summary': 's',\n"
    "               'content': 'c'}])\n"
)


def _env(home: Path) -> dict[str, str]:
    return {**os.environ, "KNOWLEDGE_OS_HOME": str(home), "PYTHONPATH": str(ROOT / "src"),
            "LOG_LEVEL": "WARNING"}


def test_quatro_processos_gravam_sem_perder_itens(tmp_path):
    home = tmp_path / "home"
    env = _env(home)
    # Prepara o banco uma vez (a criação do schema não é o que está sob teste).
    subprocess.run([sys.executable, "-c", WORKER.replace("range(25)", "range(0)"), "x", "0"],
                   env=env, cwd=ROOT, check=True, capture_output=True, timeout=120)
    procs = [
        subprocess.Popen([sys.executable, "-c", WORKER, "x", str(n)], env=env, cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for n in range(4)
    ]
    outs = [p.communicate(timeout=240) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], [o[1][-600:] for o in outs]
    db = next(home.rglob("*.db"))
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 100
    finally:
        conn.close()


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Banco em arquivo com busy_timeout curto e retentativas rápidas."""
    monkeypatch.setenv("KNOWLEDGE_OS_BUSY_TIMEOUT_MS", "50")
    monkeypatch.setattr(session_mod, "RETRY_BUDGET_S", 0.5)
    monkeypatch.setattr(session_mod, "RETRY_FIRST_WAIT_S", 0.02)
    db = tmp_path / "x.db"
    engine = create_db_engine(f"sqlite:///{db}")
    init_db(engine)
    yield engine, db
    engine.dispose()


ENTRY = {"workspace": "W", "domain": "D", "key": "k", "type": "knowledge",
         "memory_class": "working", "title": "t", "summary": "s", "content": "c"}


def test_banco_travado_vira_database_error_legivel(banco):
    engine, db = banco
    svc = ItemService(engine)
    svc.save([dict(ENTRY)])  # cria workspace/domain antes de travar
    lock = sqlite3.connect(db, isolation_level=None)
    lock.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DatabaseError, match="(?i)banco ocupado por outro processo"):
            svc.save([{**ENTRY, "title": "novo"}])
    finally:
        lock.execute("ROLLBACK")
        lock.close()


def test_contexto_nao_cai_quando_track_nao_consegue_gravar(banco):
    engine, db = banco
    ProjectService(engine).link("github.com/org/app", "W", "D")
    ws, dm = ItemService(engine).ensure_location("W", "D")
    ItemService(engine).save([{**ENTRY, "scope_paths": ["src/**"]}], default_location=(ws, dm))
    lock = sqlite3.connect(db, isolation_level=None)
    lock.execute("BEGIN IMMEDIATE")
    try:
        result = ContextService(engine).build("github.com/org/app", paths=["src/a.py"])
    finally:
        lock.execute("ROLLBACK")
        lock.close()
    assert result["linked"] is True
    assert "Em foco" in result["markdown"]


WORKER_TAG = (
    "import sys\n"
    "from knowledge_os.config import ensure_home, validate_and_init_config\n"
    "ensure_home(); validate_and_init_config()\n"
    "from knowledge_os.config import ConfigManager\n"
    "ConfigManager.load_or_create()  # o preparo cria o connections.json antes da disputa\n"
    "from knowledge_os.services.item_service import ItemService\n"
    "import pathlib, time\n"
    "n = int(sys.argv[2])\n"
    "while not pathlib.Path(sys.argv[3]).exists(): time.sleep(0.001)\n"
    "ItemService().save([{'workspace': 'W', 'domain': 'D', 'key': f'k{i}', 'type': 'knowledge',\n"
    "    'memory_class': 'working', 'title': f't{n}-{i}', 'summary': 's', 'content': 'c',\n"
    "    'tags': ['tag-nova-compartilhada']} for i in range(3)]\n"
    "    + [{'workspace': 'W', 'domain': 'D', 'key': f'p{n}', 'type': 'knowledge',\n"
    "        'memory_class': 'working', 'title': 'u', 'summary': 's', 'content': 'c',\n"
    "        'tags': ['tag-nova-compartilhada']}])\n"
)


def test_quatro_processos_com_tag_nova_e_key_nova_em_comum(tmp_path):
    home = tmp_path / "home"
    env = _env(home)
    subprocess.run([sys.executable, "-c", WORKER.replace("range(25)", "range(0)"), "x", "0"],
                   env=env, cwd=ROOT, check=True, capture_output=True, timeout=120)
    go = tmp_path / "go"
    procs = [
        subprocess.Popen([sys.executable, "-c", WORKER_TAG, "x", str(n), str(go)], env=env,
                         cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for n in range(4)
    ]
    time.sleep(3)  # todos importados e esperando a largada
    go.write_text("go")
    outs = [p.communicate(timeout=240) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], [o[1][-600:] for o in outs]
    conn = sqlite3.connect(next(home.rglob("*.db")))
    try:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3 + 4
        assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1
    finally:
        conn.close()


def test_conflito_de_unicidade_no_save_e_reexecutado(banco, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    engine, _ = banco
    svc = ItemService(engine)
    real = ItemService._save_plans
    calls = []

    def conflict_once(self, plans):
        calls.append(1)
        if len(calls) == 1:  # outro processo criou a mesma tag/key primeiro
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        return real(self, plans)

    monkeypatch.setattr(ItemService, "_save_plans", conflict_once)
    svc.save([{**ENTRY, "tags": ["nova"]}])
    assert len(calls) == 2
