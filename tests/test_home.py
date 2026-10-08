"""Home de dados único (KNOWLEDGE_OS_HOME): constantes, criação e paths relativos."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import knowledge_os.config as config
from knowledge_os.config import ConfigManager, ConnectionConfig, ConnectionsFile

ROOT = Path(__file__).resolve().parent.parent
PROBE = (
    "import json, knowledge_os.config as c;"
    "print(json.dumps({k: str(getattr(c, k)) for k in ('KNOWLEDGE_HOME','REPOS_DIR')}"
    " | {'cf': str(c.ConfigManager.CONNECTIONS_FILE)}))"
)


def _probe(cwd, env_extra, drop=()):
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_extra, PYTHONPATH=str(ROOT / "src"))
    out = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=cwd, env=env, capture_output=True, text=True,
        check=True,
    ).stdout
    return json.loads(out)


def test_home_vem_da_variavel_e_importar_nao_cria_diretorio(tmp_path):
    home = tmp_path / "meu-home"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    got = _probe(cwd, {"KNOWLEDGE_OS_HOME": str(home)})
    assert Path(got["KNOWLEDGE_HOME"]) == home
    assert Path(got["cf"]) == home / "connections.json"
    assert Path(got["REPOS_DIR"]).parent == home
    assert not home.exists()
    assert list(cwd.iterdir()) == []


def test_home_default_e_dot_knowledge_os(tmp_path):
    got = _probe(
        tmp_path,
        {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
        drop=("KNOWLEDGE_OS_HOME",),
    )
    assert Path(got["KNOWLEDGE_HOME"]) == tmp_path / ".knowledge-os"
    assert not (tmp_path / ".knowledge-os").exists()


def test_ensure_home_cria_so_o_home(tmp_path, monkeypatch):
    home = tmp_path / "novo"
    monkeypatch.setattr(config, "KNOWLEDGE_HOME", home)
    config.ensure_home()
    assert home.is_dir() and list(home.iterdir()) == []


def test_clone_path_e_a_pasta_escolhida_ou_deriva_do_id(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(config, "REPOS_DIR", home / "repos")
    assert ConnectionConfig(id="a", name="A").clone_path() == home / "repos" / "a"
    assert ConnectionConfig(id="b", name="B", path=str(tmp_path / "x")).clone_path() == (
        tmp_path / "x")


def test_sem_arquivo_nao_ha_conexao_nem_padrao(_isolated_home):
    cfg = ConfigManager.load()
    assert (cfg.default, cfg.connections) == (None, [])
    assert not (_isolated_home / "connections.json").exists()


def test_default_precisa_ser_uma_conexao_cadastrada():
    assert ConnectionsFile(default=None, connections=[]).default is None
    with pytest.raises(ValueError):
        ConnectionsFile(default="outra", connections=[])
    # "default" é o id do catálogo das versões antigas: vira "sem padrão" (ver test_config).
    assert ConnectionsFile(default="default", connections=[]).default is None
    conn = ConnectionConfig(id="a", name="A")
    assert ConnectionsFile(default="a", connections=[conn]).default == "a"


def test_save_e_atomico_sem_sobras(_isolated_home):
    ConfigManager.save(ConfigManager.create_default_config())
    ConfigManager.save(ConfigManager.create_default_config())
    assert [p.name for p in _isolated_home.iterdir()] == ["connections.json"]
    saved = json.loads((_isolated_home / "connections.json").read_text(encoding="utf-8"))
    assert saved == {"version": "1.0", "default": None, "connections": []}


def test_importacao_legada_foi_removida():
    import knowledge_os.main as main

    assert not hasattr(main, "import_legacy_connections")
