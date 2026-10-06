"""Testes de ImportExportService e das tools workspace_import / project_import."""

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from knowledge_os.db.models import Artifact, Item, Project, Relation, Workspace
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.artifact_service import ArtifactService
from knowledge_os.services.import_export_service import ImportExportService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.relation_service import RelationService


@pytest.fixture
def art_dir(tmp_path, monkeypatch):
    d = tmp_path / "artifacts"
    d.mkdir()
    monkeypatch.setattr("knowledge_os.services.artifact_service.ARTIFACTS_DIR", d)
    monkeypatch.setattr("knowledge_os.services.import_export_service.ARTIFACTS_DIR", d)
    return d


@pytest.fixture
def populated(test_engine, test_session, sample_workspace, sample_project, art_dir, tmp_path):
    """Workspace com 2 projects, 3 items (tags/labels), 2 relações e 1 artifact."""
    items = ItemService(test_engine)
    dm2 = Project(id=str(uuid.uuid4()), workspace_id=sample_workspace.id, name="Outro")
    test_session.add(dm2)
    test_session.commit()
    kw = dict(
        workspace_id=sample_workspace.id, type="rule", memory_class="longterm",
        summary="s", content="c",
    )
    a = items.create(
        project_id=sample_project.id, title="A", tags=["t1", "t2"], labels=["official"],
        confidence=70, importance=3, **kw,
    )
    b = items.create(project_id=sample_project.id, title="B", tags=["t1"], **kw)
    c = items.create(project_id=dm2.id, title="C", **kw)
    RelationService(test_session).create(a.id, b.id, "depends_on")
    RelationService(test_session).create(a.id, c.id, "references")
    f = tmp_path / "anexo.bin"
    f.write_bytes(b"\x00\x01binario-real\xff")
    art = ArtifactService(test_session, artifacts_dir=art_dir).attach(a.id, str(f))
    return {
        "ws": sample_workspace, "d1": sample_project, "d2": dm2, "items": (a, b, c),
        "art": art, "file": f,
    }


def _zip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def _write(tmp_path, data: bytes) -> str:
    p = tmp_path / f"{uuid.uuid4()}.zip"
    p.write_bytes(data)
    return str(p)


def _build_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_export_workspace_estrutura(test_session, populated):
    data = ImportExportService(test_session).export_workspace(populated["ws"].id)
    z = _zip(data)
    assert {"manifest.json", "workspace.json", "relations.json"} <= set(z.namelist())
    assert f"artifacts/{populated['art'].id}" in z.namelist()
    man = json.loads(z.read("manifest.json"))
    assert man["version"] == "1.0" and man["type"] == "workspace"
    assert man["name"] == "TestWorkspace" and man["exported_at"]
    assert man["counts"] == {"projects": 2, "items": 3, "relations": 2, "artifacts": 1}
    wj = json.loads(z.read("workspace.json"))
    assert set(wj) >= {"workspace", "projects", "items", "relations"}
    assert len(wj["items"]) == 3 and len(json.loads(z.read("relations.json"))) == 2
    assert z.read(f"artifacts/{populated['art'].id}") == populated["file"].read_bytes()


def test_export_workspace_inexistente(test_session):
    with pytest.raises(NotFoundError):
        ImportExportService(test_session).export_workspace("nao-existe")


def test_roundtrip_workspace_ids_novos_semantica_mantida(
    test_session, populated, tmp_path, art_dir
):
    svc = ImportExportService(test_session)
    data = svc.export_workspace(populated["ws"].id)
    old_ids = {i.id for i in populated["items"]}
    # nome de workspace é único: remove o original para reimportar o mesmo conteúdo
    test_session.delete(test_session.get(Workspace, populated["ws"].id))
    test_session.commit()
    ws = svc.import_workspace(_write(tmp_path, data))
    assert ws.id != populated["ws"].id and ws.name == "TestWorkspace"
    doms = {
        d.name: d
        for d in test_session.scalars(select(Project).where(Project.workspace_id == ws.id))
    }
    assert set(doms) == {"TestProject", "Outro"}
    assert doms["TestProject"].id != populated["d1"].id
    items = {
        i.title: i for i in test_session.scalars(select(Item).where(Item.workspace_id == ws.id))
    }
    assert set(items) == {"A", "B", "C"}
    assert not ({i.id for i in items.values()} & old_ids)
    assert items["A"].project_id == doms["TestProject"].id
    assert items["C"].project_id == doms["Outro"].id
    assert sorted(t.name for t in items["A"].tags) == ["t1", "t2"]
    assert [lb.name for lb in items["A"].labels] == ["official"]
    assert (items["A"].confidence, items["A"].importance) == (70, 3)
    rels = {
        (r.source_item_id, r.target_item_id, r.relation_type)
        for r in test_session.scalars(
            select(Relation).where(Relation.source_item_id.in_([i.id for i in items.values()]))
        )
    }
    assert rels == {
        (items["A"].id, items["B"].id, "depends_on"),
        (items["A"].id, items["C"].id, "references"),
    }
    arts = list(test_session.scalars(select(Artifact).where(Artifact.item_id == items["A"].id)))
    assert len(arts) == 1 and arts[0].id != populated["art"].id
    assert arts[0].filename == "anexo.bin"
    assert (art_dir / arts[0].file_path).read_bytes() == populated["file"].read_bytes()


def test_import_workspace_nome_duplicado_nao_altera_nada(
    test_session, populated, tmp_path, art_dir
):
    svc = ImportExportService(test_session)
    path = _write(tmp_path, svc.export_workspace(populated["ws"].id))
    n_files = len(list(art_dir.iterdir()))
    with pytest.raises(ValidationError):
        svc.import_workspace(path)
    assert len(list(art_dir.iterdir())) == n_files
    assert len(list(test_session.scalars(select(Workspace)))) == 1


def test_import_workspace_arquivo_invalido(test_session, tmp_path):
    svc = ImportExportService(test_session)
    with pytest.raises(NotFoundError):
        svc.import_workspace(str(tmp_path / "nada.zip"))
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"isso nao e zip")
    with pytest.raises(ValidationError):
        svc.import_workspace(str(bad))
    manifest = json.dumps({"version": "1.0", "type": "workspace"})
    only_manifest = _build_zip({"manifest.json": manifest})
    with pytest.raises(ValidationError):
        svc.import_workspace(_write(tmp_path, only_manifest))


def test_import_rejeita_tipo_trocado(test_session, populated, tmp_path):
    svc = ImportExportService(test_session)
    dom = svc.export_project(populated["ws"].id, populated["d1"].id)
    with pytest.raises(ValidationError):
        svc.import_workspace(_write(tmp_path, dom))
    ws_zip = svc.export_workspace(populated["ws"].id)
    with pytest.raises(ValidationError):
        svc.import_project(populated["ws"].id, _write(tmp_path, ws_zip))


def test_export_project_so_project_e_seus_items(test_session, populated):
    data = ImportExportService(test_session).export_project(populated["ws"].id, populated["d1"].id)
    z = _zip(data)
    man = json.loads(z.read("manifest.json"))
    assert man["type"] == "project" and man["name"] == "TestProject"
    assert man["counts"]["items"] == 2
    dj = json.loads(z.read("project.json"))
    assert {i["title"] for i in dj["items"]} == {"A", "B"}
    # a relação A->C sai do project; só A->B é mantida
    assert [r["relation_type"] for r in json.loads(z.read("relations.json"))] == ["depends_on"]
    assert f"artifacts/{populated['art'].id}" in z.namelist()


def test_export_project_inexistente(test_session, populated):
    with pytest.raises(NotFoundError):
        ImportExportService(test_session).export_project(populated["ws"].id, "nao-existe")


def test_import_project_em_outro_workspace(test_session, populated, tmp_path, art_dir):
    svc = ImportExportService(test_session)
    path = _write(tmp_path, svc.export_project(populated["ws"].id, populated["d1"].id))
    other = Workspace(id=str(uuid.uuid4()), name="Destino")
    test_session.add(other)
    test_session.commit()
    dm = svc.import_project(other.id, path)
    assert dm.id != populated["d1"].id and dm.workspace_id == other.id and dm.name == "TestProject"
    items = list(test_session.scalars(select(Item).where(Item.project_id == dm.id)))
    assert {i.title for i in items} == {"A", "B"}
    assert all(i.workspace_id == other.id for i in items)
    by = {i.title: i for i in items}
    rel = test_session.scalars(select(Relation).where(Relation.source_item_id == by["A"].id)).one()
    assert rel.target_item_id == by["B"].id
    art = test_session.scalars(select(Artifact).where(Artifact.item_id == by["A"].id)).one()
    assert (art_dir / art.file_path).read_bytes() == populated["file"].read_bytes()


def test_import_project_nome_duplicado_e_workspace_inexistente(test_session, populated, tmp_path):
    svc = ImportExportService(test_session)
    path = _write(tmp_path, svc.export_project(populated["ws"].id, populated["d1"].id))
    with pytest.raises(ValidationError):
        svc.import_project(populated["ws"].id, path)
    with pytest.raises(NotFoundError):
        svc.import_project("nao-existe", path)


def test_import_artifact_com_membro_ausente_no_zip_falha_limpo(test_session, tmp_path, art_dir):
    payload = {
        "workspace": {"name": "Z"},
        "projects": [{"id": "d", "name": "D"}],
        "items": [{
            "id": "i", "project_id": "d", "type": "rule", "memory_class": "longterm",
            "title": "t", "summary": "s", "content": "c", "tags": [], "labels": [],
        }],
        "relations": [],
        "artifacts": [{"id": "../../evil", "item_id": "i", "filename": "e"}],
    }
    data = _build_zip({
        "manifest.json": json.dumps({"version": "1.0", "type": "workspace", "name": "Z"}),
        "workspace.json": json.dumps(payload),
        "relations.json": "[]",
    })
    with pytest.raises(ValidationError):
        ImportExportService(test_session).import_workspace(_write(tmp_path, data))
    assert test_session.scalar(select(Workspace.id).where(Workspace.name == "Z")) is None
    assert list(art_dir.iterdir()) == []


