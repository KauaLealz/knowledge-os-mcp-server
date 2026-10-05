"""Testes de ArtifactService, schemas e artifact_tools."""

import asyncio
import base64
import json

import pytest
from fastmcp import Client, FastMCP
from pydantic import ValidationError as PydanticValidationError

from src.db.models import Artifact
from src.exceptions import NotFoundError, ValidationError
from src.mcp import artifact_tools
from src.schemas.artifact_schemas import ArtifactCreate, ArtifactResponse
from src.services.artifact_service import ArtifactService
from tests.helpers_mcp import client_call, tools_by_name


@pytest.fixture
def art_dir(tmp_path):
    d = tmp_path / "artifacts"
    d.mkdir()
    return d


@pytest.fixture
def src_file(tmp_path):
    p = tmp_path / "nota.txt"
    p.write_bytes(b"conteudo real \x00\x01 binario")
    return p


@pytest.fixture
def svc(test_session, art_dir):
    return ArtifactService(test_session, artifacts_dir=art_dir)


def test_attach_copia_arquivo_com_uuid_e_registra(svc, sample_item, src_file, art_dir):
    art = svc.attach(sample_item.id, str(src_file))
    assert art.item_id == sample_item.id
    assert art.filename == "nota.txt"
    assert art.file_size == src_file.stat().st_size
    assert art.mime_type == "text/plain"
    assert art.file_path != "nota.txt" and len(art.file_path) == 36
    assert (art_dir / art.file_path).read_bytes() == src_file.read_bytes()


def test_attach_item_inexistente(svc, src_file, art_dir):
    with pytest.raises(NotFoundError):
        svc.attach("nao-existe", str(src_file))
    assert list(art_dir.iterdir()) == []


def test_attach_arquivo_inexistente(svc, sample_item, tmp_path):
    with pytest.raises(NotFoundError):
        svc.attach(sample_item.id, str(tmp_path / "x.bin"))


def test_attach_diretorio_invalido(svc, sample_item, tmp_path):
    with pytest.raises(ValidationError):
        svc.attach(sample_item.id, str(tmp_path))


def test_list_e_get(svc, sample_item, src_file):
    a = svc.attach(sample_item.id, str(src_file))
    b = svc.attach(sample_item.id, str(src_file))
    assert {x.id for x in svc.list(sample_item.id)} == {a.id, b.id}
    meta, data = svc.get(a.id)
    assert meta.id == a.id and data == src_file.read_bytes()


def test_list_item_inexistente(svc):
    with pytest.raises(NotFoundError):
        svc.list("nao-existe")


def test_get_inexistente_e_arquivo_sumido(svc, sample_item, src_file, art_dir):
    with pytest.raises(NotFoundError):
        svc.get("nao-existe")
    a = svc.attach(sample_item.id, str(src_file))
    (art_dir / a.file_path).unlink()
    with pytest.raises(NotFoundError):
        svc.get(a.id)


def test_get_rejeita_path_traversal(svc, test_session, sample_item, tmp_path):
    (tmp_path / "segredo.txt").write_text("x")
    row = Artifact(
        id="a1", item_id=sample_item.id, filename="s", file_path="../segredo.txt", file_size=1
    )
    test_session.add(row)
    test_session.commit()
    with pytest.raises(ValidationError):
        svc.get("a1")


def test_schemas():
    assert ArtifactCreate(item_id="i", file_path="/x").item_id == "i"
    with pytest.raises(PydanticValidationError):
        ArtifactCreate(item_id="", file_path="/x")
    assert set(ArtifactResponse.model_fields) == {
        "id", "item_id", "filename", "file_size", "mime_type", "created_at",
    }


class TestTools:
    @pytest.fixture
    def server(self, monkeypatch, test_engine, art_dir):
        monkeypatch.setattr("src.services._common.get_engine", lambda: test_engine)
        monkeypatch.setattr("src.services.artifact_service.ARTIFACTS_DIR", art_dir)
        m = FastMCP(name="t")
        artifact_tools.register(m)
        return m

    def _call(self, server, name, args):
        out = []
        for block in client_call(server, name, args):
            value = json.loads(block.text)
            out.extend(value if isinstance(value, list) else [value])
        return out

    def test_registra_3_tools(self, server):
        async def run():
            async with Client(server) as client:
                return {t.name for t in await client.list_tools()}

        assert asyncio.run(run()) == {"artifact_attach", "artifact_list", "artifact_get"}

    def test_fluxo_attach_list_get(self, server, sample_item, src_file):
        att = self._call(
            server, "artifact_attach", {"item_id": sample_item.id, "file_path": str(src_file)}
        )[0]
        assert att["filename"] == "nota.txt" and att["file_size"] == src_file.stat().st_size
        listed = self._call(server, "artifact_list", {"item_id": sample_item.id})
        assert [x["id"] for x in listed] == [att["id"]]
        got = self._call(server, "artifact_get", {"artifact_id": att["id"]})[0]
        assert base64.b64decode(got["content_base64"]) == src_file.read_bytes()
        assert got["artifact"]["id"] == att["id"]


def test_main_registra_40_tools():
    import src.main as main

    main.register_all_tools()
    names = set(tools_by_name(main.mcp))
    assert len(names) == 44  # 32 (T1-T5) + 6 de connection (T7) + 2 (T9) + 4 do cérebro
    assert {"health_check", "item_search", "artifact_get", "workspace_import"} <= names
