"""Testes do config de conexões (connections.json no home)."""

import pytest

from knowledge_os.config import ConfigManager, ConnectionConfig, ConnectionsFile


def test_connection_config_valid():
    conn = ConnectionConfig(id="local", name="Local")
    assert conn.remote_url is None
    assert conn.review_mode == "direct"


def test_connection_config_id_invalid():
    with pytest.raises(ValueError):
        ConnectionConfig(id="INVALID_ID", name="Test")


def test_connection_config_review_mode_invalido():
    with pytest.raises(ValueError):
        ConnectionConfig(id="pg", name="PG", review_mode="sync")


def test_connections_file_default_exists():
    with pytest.raises(ValueError):
        ConnectionsFile(version="1.0", default="nonexistent", connections=[])


def _remote(**kw):
    return ConnectionConfig(
        id="gh", name="GH", remote_url="https://github.com/acme/repo.git", **kw
    )


def test_review_mode_default_e_customizavel():
    assert _remote().review_mode == "direct"
    assert _remote(review_mode="pr").review_mode == "pr"


def test_erro_do_ls_remote_nao_ecoa_credencial_embutida_na_url():
    # Não há mais campo de senha no modelo: o remote_url pode conter credencial (HTTPS
    # com token), que não deve vazar na mensagem do teste de conexão em caso de erro.
    conn = ConnectionConfig(
        id="gh", name="GH",
        remote_url="https://x-access-token:topsecret@127.0.0.1:1/acme/repo.git",
    )
    msg = ConfigManager.validate_connection(conn)["message"]
    assert "topsecret" not in msg


def test_create_default_config():
    config = ConfigManager.create_default_config()
    assert config.default is None
    assert config.connections == []


def test_load_sem_arquivo_nao_cria_nada(_isolated_home):
    config = ConfigManager.load()
    assert not (_isolated_home / "connections.json").exists()
    assert config.default is None and config.connections == []


def test_load_existing_config():
    config = ConfigManager.create_default_config()
    ConfigManager.save(config)
    loaded = ConfigManager.load()
    assert loaded.default == config.default
    assert len(loaded.connections) == len(config.connections)


def test_validate_connection_sem_remote_e_sempre_ok():
    conn = ConnectionConfig(id="local", name="Local")
    assert ConfigManager.validate_connection(conn) == {
        "status": "ok", "message": "Repositório local (sem remote)"
    }


def test_validate_connection_error_com_remote_inalcancavel():
    conn = ConnectionConfig(id="bad", name="Bad", remote_url="https://127.0.0.1:1/nope.git")
    assert ConfigManager.validate_connection(conn)["status"] == "error"


def test_json_a_mao_sem_campos_novos_assume_o_padrao():
    import json

    ConfigManager.CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ConfigManager.CONNECTIONS_FILE.write_text(
        json.dumps({"version": "1.0", "default": "gh",
                    "connections": [{"id": "gh", "name": "GH"}]}),
        encoding="utf-8",
    )
    config = ConfigManager.load()
    conn = config.get_connection("gh")
    assert conn.remote_url is None and conn.review_mode == "direct"


def test_json_com_review_mode_invalido_aponta_conexao_sem_vazar_dado():
    import json

    from knowledge_os.exceptions import ConfigError
    from knowledge_os.services.connection_service import ConnectionService

    ConfigManager.CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ConfigManager.CONNECTIONS_FILE.write_text(
        json.dumps({"version": "1.0", "default": "gh",
                    "connections": [{"id": "gh", "name": "GH", "review_mode": "sync"}]}),
        encoding="utf-8",
    )
    for call in (ConfigManager.load, ConnectionService().list):
        with pytest.raises(ConfigError) as err:
            call()
        msg = str(err.value)
        assert "gh" in msg and "review_mode" in msg
        assert msg.count("connections.json inválido") == 1


def test_conexao_sem_remote_e_valida():
    # uma connection sem remote_url é válida (repositório só local).
    ConnectionConfig(id="s", name="S")


def test_save_usa_tmp_unico_com_permissao_restrita(monkeypatch):
    import os

    opened, replaced = [], []
    real_open, real_replace = os.open, os.replace

    def spy_open(path, flags, mode=0o777, **kw):
        opened.append((str(path), mode))
        return real_open(path, flags, mode, **kw)

    def spy_replace(src, dst):
        replaced.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "replace", spy_replace)
    ConfigManager.save(ConfigManager.create_default_config())
    ConfigManager.save(ConfigManager.create_default_config())
    assert len(opened) == 2 and all(m == 0o600 for _, m in opened)
    assert opened[0][0] != opened[1][0]  # tmp único a cada save (nada de nome fixo)
    assert str(os.getpid()) in opened[0][0]
    assert not list(ConfigManager.CONNECTIONS_FILE.parent.glob("*.tmp"))


def test_save_fallback_quando_replace_falha(monkeypatch):
    import os

    def boom(src, dst):
        raise OSError("destino aberto")

    monkeypatch.setattr(os, "replace", boom)
    ConfigManager.save(ConfigManager.create_default_config())
    assert ConfigManager.load().default is None
    assert not list(ConfigManager.CONNECTIONS_FILE.parent.glob("*.tmp"))


def test_knowledge_os_home_resolve_til_e_relativo(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    code = "import knowledge_os.config as c; print(c.KNOWLEDGE_HOME)"

    def home_for(value):
        env = {**os.environ, "KNOWLEDGE_OS_HOME": value, "PYTHONPATH": str(root / "src")}
        out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())

    assert home_for("rel/../meu-home") == (tmp_path / "meu-home").resolve()
    assert home_for("~/kos-teste") == (Path.home() / "kos-teste").resolve()
