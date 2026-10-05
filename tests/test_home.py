"""Home de dados único (KNOWLEDGE_OS_HOME): constantes, criação e paths relativos."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import knowledge_os.config as config
from knowledge_os.config import CATALOG_ID, ConfigManager, ConnectionConfig, ConnectionsFile

ROOT = Path(__file__).resolve().parent.parent
PROBE = (
    "import json, knowledge_os.config as c;"
    "print(json.dumps({k: str(getattr(c, k)) for k in "
    "('KNOWLEDGE_HOME','ARTIFACTS_DIR','EXPORTS_DIR','BACKUPS_DIR','DB_PATH')}"
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
    got = _probe(cwd, {"KNOWLEDGE_OS_HOME": str(home)}, drop=("MCP_DB_PATH",))
    assert Path(got["KNOWLEDGE_HOME"]) == home
    assert Path(got["cf"]) == home / "connections.json"
    assert Path(got["DB_PATH"]) == home / "knowledge.db"
    for k in ("ARTIFACTS_DIR", "EXPORTS_DIR", "BACKUPS_DIR"):
        assert Path(got[k]).parent == home
    assert not home.exists()
    assert list(cwd.iterdir()) == []


def test_home_default_e_dot_knowledge_os(tmp_path):
    got = _probe(
        tmp_path,
        {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
        drop=("KNOWLEDGE_OS_HOME", "MCP_DB_PATH"),
    )
    assert Path(got["KNOWLEDGE_HOME"]) == tmp_path / ".knowledge-os"
    assert not (tmp_path / ".knowledge-os").exists()


def test_mcp_db_path_continua_sendo_override(tmp_path):
    got = _probe(tmp_path, {"KNOWLEDGE_OS_HOME": str(tmp_path / "h"), "MCP_DB_PATH": "/x/y.db"})
    assert got["DB_PATH"] == "/x/y.db"


def test_ensure_home_cria_home_e_subdiretorios(tmp_path, monkeypatch):
    home = tmp_path / "novo"
    monkeypatch.setattr(config, "KNOWLEDGE_HOME", home)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", home / "artifacts")
    monkeypatch.setattr(config, "EXPORTS_DIR", home / "exports")
    monkeypatch.setattr(config, "BACKUPS_DIR", home / "backups")
    config.ensure_home()
    assert {p.name for p in home.iterdir()} == {"artifacts", "exports", "backups"}


def test_sqlite_relativo_resolve_contra_o_home_em_qualquer_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    outro = tmp_path / "outro"
    outro.mkdir()
    monkeypatch.chdir(outro)
    conn = ConnectionConfig(id="a", name="A", db_type="sqlite", path="sub/a.db")
    assert conn.get_url() == f"sqlite:///{(home / 'sub' / 'a.db').as_posix()}"


def test_sqlite_absoluto_nao_muda(tmp_path):
    p = (tmp_path / "x.db").as_posix()
    conn = ConnectionConfig(id="a", name="A", db_type="sqlite", path=p)
    assert conn.get_url() == f"sqlite:///{p}"


def test_id_default_e_reservado():
    with pytest.raises(ValueError):
        ConnectionConfig(id="default", name="X", db_type="sqlite", path="x.db")


def test_primeira_execucao_cria_json_so_com_o_catalogo(_isolated_home):
    cfg = ConfigManager.load_or_create()
    assert (cfg.default, cfg.connections) == (CATALOG_ID, [])
    saved = json.loads((_isolated_home / "connections.json").read_text(encoding="utf-8"))
    assert saved["default"] == "default" and saved["connections"] == []
    assert "sqlite_local" not in json.dumps(saved)


def test_default_aceita_catalogo_mas_recusa_id_desconhecido():
    assert ConnectionsFile(default="default", connections=[]).default == "default"
    with pytest.raises(ValueError):
        ConnectionsFile(default="outro", connections=[])


def test_save_e_atomico_sem_sobras(_isolated_home):
    ConfigManager.save(ConfigManager.create_default_config())
    ConfigManager.save(ConfigManager.create_default_config())
    assert [p.name for p in _isolated_home.iterdir()] == ["connections.json"]


def test_sqlite_local_e_legado_foram_removidos():
    import knowledge_os.main as main

    assert not hasattr(main, "import_legacy_connections")
    assert "sqlite_local" not in main.INSTRUCTIONS_FILE.read_text(encoding="utf-8")
