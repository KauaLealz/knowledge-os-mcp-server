"""Vários processos gravando na mesma pasta: trava entre processos e contador best-effort."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from knowledge_os.exceptions import StorageError
from knowledge_os.services.brain import Brain
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.repo_service import RepoService
from knowledge_os.storage import access, local_state

ROOT = Path(__file__).resolve().parent.parent

WORKER = (
    "import sys\n"
    "from knowledge_os.services.item_service import ItemService\n"
    "n = int(sys.argv[2])\n"
    "svc = ItemService()\n"
    "for i in range(8):\n"
    "    svc.save([{'workspace': 'W', 'project': 'D', 'key': f'p{n}/{i}', 'type': 'howto',\n"
    "               'title': f't{n}-{i}', 'summary': 's',\n"
    "               'content': 'c'}])\n"
)


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "connections.json").write_text(json.dumps({
        "version": "1.0", "default": "d",
        "connections": [{"id": "d", "name": "Dados", "path": str(tmp_path / "dados")}],
    }), encoding="utf-8")
    return {**os.environ, "KNOWLEDGE_OS_HOME": str(home), "PYTHONPATH": str(ROOT / "src"),
            "LOG_LEVEL": "WARNING"}


def _records(env: dict[str, str]) -> list[str]:
    code = ("from knowledge_os.services.brain import Brain\n"
            "print('\\n'.join(sorted(r.key or '' for r in Brain().snapshot.records.values())))")
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True,
                         text=True, timeout=120, check=True).stdout
    return [line for line in out.splitlines() if line]


def test_quatro_processos_gravam_sem_perder_itens(tmp_path):
    env = _env(tmp_path)
    procs = [
        subprocess.Popen([sys.executable, "-c", WORKER, "x", str(n)], env=env, cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for n in range(4)
    ]
    outs = [p.communicate(timeout=300) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], [o[1][-600:] for o in outs]
    assert len(_records(env)) == 32
    status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path / "dados",
                            capture_output=True, text=True, check=True).stdout
    assert status.strip() == ""  # tudo commitado, nada pela metade


WORKER_TAG = (
    "import sys\n"
    "from knowledge_os.services.item_service import ItemService\n"
    "import pathlib, time\n"
    "n = int(sys.argv[2])\n"
    "while not pathlib.Path(sys.argv[3]).exists(): time.sleep(0.001)\n"
    "ItemService().save([{'workspace': 'W', 'project': 'D', 'key': f'k{i}', 'type': 'howto',\n"
    "    'title': f't{n}-{i}', 'summary': 's', 'content': 'c',\n"
    "    'tags': ['tag-nova-compartilhada']} for i in range(3)]\n"
    "    + [{'workspace': 'W', 'project': 'D', 'key': f'p{n}', 'type': 'howto',\n"
    "        'title': 'u', 'summary': 's', 'content': 'c',\n"
    "        'tags': ['tag-nova-compartilhada']}])\n"
)


def test_quatro_processos_com_tag_nova_e_key_nova_em_comum(tmp_path):
    env = _env(tmp_path)
    go = tmp_path / "go"
    procs = [
        subprocess.Popen([sys.executable, "-c", WORKER_TAG, "x", str(n), str(go)], env=env,
                         cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for n in range(4)
    ]
    time.sleep(3)  # todos importados e esperando a largada
    go.write_text("go")
    outs = [p.communicate(timeout=300) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], [o[1][-600:] for o in outs]
    keys = _records(env)
    assert sorted(keys) == ["k0", "k1", "k2", "p0", "p1", "p2", "p3"]  # key comum não duplica


def test_trava_presa_de_outro_processo_vira_erro_legivel(conn, monkeypatch):
    monkeypatch.setattr(access, "LOCK_TIMEOUT_S", 0.3)
    with access.folder_lock(conn.clone_path()):
        with pytest.raises(StorageError, match="Outra gravação"):
            with access.folder_lock(conn.clone_path(), timeout_s=0.3):
                pass


def test_trava_abandonada_e_retomada(conn, monkeypatch):
    monkeypatch.setattr(access, "LOCK_STALE_S", 0.0)
    with access.folder_lock(conn.clone_path()):
        with access.folder_lock(conn.clone_path(), timeout_s=0.5):
            pass  # o dono "morreu": a trava velha é retomada


def test_editar_dentro_de_edicao_na_mesma_thread_nao_trava(conn):
    brain = Brain()
    with brain.editing():
        with Brain().editing():
            pass


def test_contexto_nao_cai_quando_o_contador_nao_consegue_gravar(conn, monkeypatch):
    from knowledge_os.services.context_service import ContextService  # pacote: fase 5

    RepoService().link("github.com/org/app", "W", "D")
    ItemService().save([{"key": "k", "type": "howto", "title": "t", "summary": "s",
                         "content": "c", "scope_paths": ["src/**"]}], default_location=("W", "D"))

    def boom(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(local_state, "_write", boom)
    result = ContextService().build("github.com/org/app", paths=["src/a.py"])
    assert result["linked"] is True
    assert "Em foco" in result["markdown"]
