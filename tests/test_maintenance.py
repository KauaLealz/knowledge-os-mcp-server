"""Manutenção diária: memória temporária vencida sai dos arquivos e a remoção é publicada."""

import subprocess
from datetime import timedelta

import pytest

from knowledge_os import config
from knowledge_os.services import maintenance
from knowledge_os.services.brain import Brain, utcnow
from knowledge_os.services.item_service import ItemService
from tests.conftest import make_connection

BASE = {"workspace": "W", "project": "D", "type": "knowledge", "summary": "s", "content": "c"}


def _save(**entry):
    return ItemService().save([{**BASE, **entry}])[0]["id"]


def _age(data_dir, item_id, days):
    """Recua o `updated_at` do arquivo do item em `days` dias (como se fosse antigo)."""
    item = ItemService().get(item_id)
    path = data_dir / item.path
    old = item.updated_at.isoformat() + "Z"
    new = (item.updated_at - timedelta(days=days)).isoformat() + "Z"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_apaga_so_ephemeral_vencido_e_publica(conn, data_dir):
    vencido = _save(key="nota/velha", title="Velha", memory_class="ephemeral", ttl_days=1)
    vivo = _save(key="nota/nova", title="Nova", memory_class="ephemeral", ttl_days=30)
    antigo = _save(key="regra/antiga", title="Antiga", memory_class="longterm")
    _age(data_dir, vencido, 2)
    _age(data_dir, vivo, 2)
    _age(data_dir, antigo, 400)

    removed = maintenance.purge_expired_ephemeral(Brain(), utcnow())

    assert removed == 1
    ids = set(Brain().snapshot.records)
    assert ids == {vivo, antigo}
    assert not (data_dir / "w" / "d" / "nota" / "velha.md").exists()
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=data_dir, capture_output=True,
                         text=True, check=True).stdout
    assert "ephemeral vencido" in log


def test_sem_vencidos_nao_publica_nada(conn, data_dir):
    _save(key="nota", title="Nota", memory_class="ephemeral", ttl_days=30)
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=data_dir, capture_output=True,
                            text=True, check=True).stdout
    assert maintenance.purge_expired_ephemeral(Brain(), utcnow()) == 0
    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=data_dir, capture_output=True,
                           text=True, check=True).stdout
    assert before == after


def test_run_daily_roda_uma_vez_por_dia_em_todas_as_conexoes(tmp_path, data_dir):
    _save(key="a", title="A", memory_class="ephemeral", ttl_days=1)
    outra = make_connection(tmp_path / "outra", conn_id="outra", name="Outra", default=False)
    ItemService(connection_id="outra").save(
        [{**BASE, "key": "b", "title": "B", "memory_class": "ephemeral", "ttl_days": 1}])

    later = utcnow() + timedelta(days=3)
    first = maintenance.run_daily(now=later)
    assert first == {"ran": True, "expired": 2}
    assert maintenance.run_daily(now=later) == {"ran": False}
    assert (config.KNOWLEDGE_HOME / maintenance.MARKER_NAME).read_text() == later.strftime(
        "%Y-%m-%d")
    assert Brain().snapshot.records == {}
    assert Brain(outra.id).snapshot.records == {}


def test_run_daily_sem_conexao_so_marca(_isolated_home):
    assert maintenance.run_daily() == {"ran": True, "expired": 0}


def test_conexao_com_problema_nao_para_as_outras(tmp_path, conn, monkeypatch):
    make_connection(tmp_path / "quebrada", conn_id="quebrada", name="Q", default=False)
    _save(key="a", title="A", memory_class="ephemeral", ttl_days=1)
    real = maintenance.purge_expired_ephemeral

    def flaky(brain, now):
        if brain.cid == "quebrada":
            raise RuntimeError("fora do ar")
        return real(brain, now)

    monkeypatch.setattr(maintenance, "purge_expired_ephemeral", flaky)
    assert maintenance.run_daily(now=utcnow() + timedelta(days=3))["expired"] == 1


@pytest.mark.parametrize("cmd", ["backup"])
def test_comando_de_copia_de_seguranca_nao_existe_mais(cmd):
    from knowledge_os.cli import BRAIN_COMMANDS

    assert cmd not in BRAIN_COMMANDS
