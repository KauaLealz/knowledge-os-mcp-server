"""Escrita do segundo cérebro pelo ItemService: arquivo no caminho da key, lote, similares,
segredos, supersedes, ttl, nomes de workspace/project e itens duplicados na pasta.

O contrato do `save` v2 (validação, avisos, upsert, mover) está em test_items_v2.py.
"""

from datetime import timedelta

import pytest

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.brain import utcnow
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.services.secret_guard import find_secret
from knowledge_os.services.workspace_service import WorkspaceService

FIELDS = dict(type="rule", title="Money em pagamentos", summary="Valores sempre em Money",
              content="Use Money, nunca double.")


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


@pytest.fixture
def sample_item(sample_workspace, sample_project):
    return ItemService().create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                                type="howto", title="Test Item", summary="Test summary",
                                content="Spring beans and conditional logic")


def _md_files(data_dir):
    return sorted(p.relative_to(data_dir).as_posix() for p in data_dir.rglob("*.md")
                  if ".git" not in p.parts)


def test_upsert_grava_o_arquivo_no_caminho_da_key(svc, sample_workspace, sample_project,
                                                    data_dir):
    svc.save([{"key": "rule/money", **FIELDS}],
             default_location=(sample_workspace.id, sample_project.id))
    text = (data_dir / "testworkspace" / "testproject" / "rule" / "money.md").read_text(
        encoding="utf-8")
    assert "workspace: TestWorkspace" in text and "Use Money, nunca double." in text


def test_lote_cria_local_e_atualiza_numa_publicacao(svc, data_dir):
    rows = svc.save([
        {"workspace": "Polara", "project": "projpro", "key": "rule/a", **FIELDS},
        {"workspace": "Polara", "project": "projpro", "key": "rule/b", **FIELDS,
         "title": "Outra"},
    ])
    assert [r["action"] for r in rows] == ["created", "created"]
    rows = svc.save([
        {"workspace": "Polara", "project": "projpro", "key": "rule/a", "summary": "nova"},
        {"workspace": "Polara", "project": "projpro", "key": "rule/c", **FIELDS},
    ])
    assert [r["action"] for r in rows] == ["updated", "created"]
    assert [w.name for w in WorkspaceService().list()] == ["Polara"]
    assert _md_files(data_dir) == ["polara/projpro/rule/a.md", "polara/projpro/rule/b.md",
                                   "polara/projpro/rule/c.md"]


def test_similar_avisa_titulo_parecido(svc, sample_workspace, sample_project):
    svc.create(workspace_id=sample_workspace.id, project_id=sample_project.id, **FIELDS)
    found = svc.similar(sample_workspace.id, "pagamentos em Money")
    assert found and found[0]["title"] == FIELDS["title"]


def test_tags_editaveis(svc, sample_workspace, sample_project):
    it = svc.create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                    tags=["a"], **FIELDS)
    it = svc.update(it.id, tags=["c", "b"])
    assert it.tags == ["b", "c"]


@pytest.mark.parametrize("texto", [
    "use AKIAABCDEFGHIJKLMNOP no deploy",
    "-----BEGIN RSA PRIVATE KEY-----",
    "token ghp_" + "a" * 36,
    "password=SuperSecreta123",
    "amqp://user:minhasenha@fila/x",
])
def test_segredo_bloqueado_sem_eco(svc, sample_workspace, sample_project, texto):
    with pytest.raises(ValidationError) as exc:
        svc.create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                   **{**FIELDS, "content": texto})
    assert "segredo" in str(exc.value)
    assert texto not in str(exc.value)


@pytest.mark.parametrize("texto", [
    "password=<sua-senha>", "senha: ${DB_PASSWORD}", "amqp://user:***@fila/x",
    "a senha fica no cofre", "api_key no .env.example",
])
def test_placeholder_nao_e_segredo(texto):
    assert find_secret(texto) is None


def test_supersedes_arquiva_o_antigo(svc, sample_workspace, sample_project):
    loc = (sample_workspace.id, sample_project.id)
    velho, novo = svc.save([{**FIELDS, "key": "howto/deploy", "type": "howto",
                             "title": "Deploy manual"},
                            {**FIELDS, "key": "howto/deploy-ci", "type": "howto",
                             "title": "Deploy no CI"}], default_location=loc)
    RelationService().create([{"source": "howto/deploy-ci", "type": "supersedes",
                               "target": "howto/deploy"}], viewpoint=loc)
    assert svc.get(velho["id"]).status == "archived"
    found = svc.search("deploy", viewpoint=loc)["results"]
    assert [r["id"] for r in found] == [novo["id"]]


def test_ttl_renovado_conta_de_novo(svc, sample_workspace, sample_project):
    item = svc.create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                      ttl_days=1, **FIELDS)
    assert item.expires_at == item.updated_at + timedelta(days=1)
    renewed = svc.update(item.id, ttl_days=30)
    assert renewed.expires_at > item.expires_at
    assert timedelta(days=29) < renewed.expires_at - utcnow() <= timedelta(days=30)
    assert svc.update(item.id, ttl_days=None).expires_at is None


def test_project_e_workspace_do_lote_reaproveitados(svc, sample_workspace, sample_project):
    svc.save([{"workspace": sample_workspace.name, "project": sample_project.name,
               "key": "rule/x", **FIELDS}])
    assert [p.name for p in svc.brain().snapshot.projects(sample_workspace.id)] == [
        sample_project.name]


def test_nome_que_difere_so_na_caixa_cai_no_mesmo_workspace(svc, sample_workspace,
                                                            sample_project):
    svc.save([{"workspace": "testworkspace", "project": "TESTPROJECT", "key": "rule/x",
               **FIELDS}])
    item = svc.get_by_key(sample_workspace.id, sample_project.id, "rule/x")
    assert (item.workspace, item.project) == ("TestWorkspace", "TestProject")


def test_apagar_workspace_e_project_com_tags_relacoes_e_link(conn, data_dir):
    from knowledge_os.services.project_service import ProjectService
    from knowledge_os.services.repo_service import RepoService

    svc = ItemService()
    svc.save([{"workspace": "W", "project": "D", "key": "rule/a", **FIELDS, "tags": ["t"]}])
    svc.save([{"workspace": "W", "project": "D2", "key": "rule/b", **FIELDS},
              {"workspace": "W", "project": "D2", "key": "rule/b2", **FIELDS}])
    RelationService().create([{"source": "rule/b", "type": "related_to",
                               "target": "rule/b2"}], viewpoint=("w", "d2"))
    RepoService().link("github.com/o/r", "W", "D")
    assert ProjectService().delete("w", "D2") is True
    assert WorkspaceService().delete("W") is True
    assert _md_files(data_dir) == []
    assert RepoService().resolve("github.com/o/r") is None


def _duplica(data_dir, item_id: str, svc: ItemService, delta_ns: int = 2_000_000_000):
    """Cópia do arquivo do item (mesmo id) em outro caminho; mais recente, vira a vencedora."""
    import os

    original = data_dir / svc.get(item_id).path
    copia = original.parent / "copia.md"
    copia.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    st = original.stat()
    os.utime(copia, ns=(st.st_atime_ns, st.st_mtime_ns + delta_ns))
    return original, copia


def test_apagar_item_duplicado_remove_todos_os_arquivos_do_id(svc, sample_item, data_dir):
    original, copia = _duplica(data_dir, sample_item.id, svc)
    assert svc.get(sample_item.id).path.endswith("copia.md")
    svc.remove(sample_item.id)
    assert not original.exists() and not copia.exists()
    with pytest.raises(NotFoundError):
        svc.get(sample_item.id)  # não "volta" pelo outro arquivo


@pytest.mark.parametrize("delta_ns", [2_000_000_000, -2_000_000_000])
def test_regravar_item_duplicado_deixa_um_arquivo_so(svc, sample_item, data_dir, delta_ns):
    original, copia = _duplica(data_dir, sample_item.id, svc, delta_ns)
    svc.update(sample_item.id, title="Titulo novo")
    sobrou = [p for p in (original, copia) if p.exists()]
    assert len(sobrou) == 1
    assert svc.get(sample_item.id).title == "Titulo novo"
