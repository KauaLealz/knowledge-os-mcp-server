"""attach e import não leem arquivos de dentro do home de dados (ex.: connections.json)."""

import os

import pytest

import knowledge_os.config as config
from knowledge_os.config import ConfigManager
from knowledge_os.exceptions import ValidationError
from knowledge_os.services.artifact_service import ArtifactService
from knowledge_os.services.import_export_service import ImportExportService


@pytest.fixture
def home_file(_isolated_home):
    ConfigManager.save(ConfigManager.create_default_config())
    return ConfigManager.CONNECTIONS_FILE


@pytest.fixture
def svc(test_session, tmp_path):
    return ArtifactService(test_session, artifacts_dir=tmp_path / "artifacts")


def test_attach_do_connections_json_e_recusado(svc, sample_item, home_file):
    with pytest.raises(ValidationError, match="dentro do home de dados"):
        svc.attach(sample_item.id, str(home_file))


def test_attach_via_dotdot_e_recusado(svc, sample_item, home_file):
    sub = home_file.parent / "sub"
    sub.mkdir()
    with pytest.raises(ValidationError, match="dentro do home de dados"):
        svc.attach(sample_item.id, str(sub / ".." / "connections.json"))


def test_attach_via_symlink_e_recusado(svc, sample_item, home_file, tmp_path):
    link = tmp_path / "inocente.txt"
    try:
        os.symlink(home_file, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink indisponível neste ambiente")
    with pytest.raises(ValidationError, match="dentro do home de dados"):
        svc.attach(sample_item.id, str(link))


def test_attach_de_fora_do_home_funciona(svc, sample_item, tmp_path):
    f = tmp_path / "nota.txt"
    f.write_text("oi")
    assert svc.attach(sample_item.id, str(f)).filename == "nota.txt"


def test_import_zip_em_exports_dir_passa_da_guarda(test_session, home_file, monkeypatch):
    exports = home_file.parent / "exports"
    exports.mkdir()
    monkeypatch.setattr(config, "EXPORTS_DIR", exports)
    bad = exports / "x.zip"
    bad.write_bytes(b"nao e zip")
    with pytest.raises(ValidationError, match="ZIP válido"):
        ImportExportService(test_session).import_workspace(str(bad))


def test_import_zip_em_outro_lugar_do_home_e_recusado(test_session, home_file, monkeypatch):
    monkeypatch.setattr(config, "EXPORTS_DIR", home_file.parent / "exports")
    with pytest.raises(ValidationError, match="dentro do home de dados"):
        ImportExportService(test_session).import_workspace(str(home_file))
    with pytest.raises(ValidationError, match="dentro do home de dados"):
        ImportExportService(test_session).import_domain("ws", str(home_file))


def test_import_zip_fora_do_home_passa_da_guarda(test_session, tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"nao e zip")
    with pytest.raises(ValidationError, match="ZIP válido"):
        ImportExportService(test_session).import_workspace(str(bad))
