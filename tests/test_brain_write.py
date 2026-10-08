"""Escrita do segundo cérebro: upsert, lote, similares, segredos, ciclo de vida (plumb-brain T4)."""

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.memory_service import MemoryService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.services.secret_guard import find_secret
from knowledge_os.services.workspace_service import WorkspaceService

FIELDS = dict(type="rule", memory_class="working", title="Money em pagamentos",
              summary="Valores sempre em Money", content="Use Money, nunca double.")


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _md_files(data_dir):
    return sorted(p.relative_to(data_dir).as_posix() for p in data_dir.rglob("*.md")
                  if ".git" not in p.parts)


def test_upsert_cria_atualiza_e_reconhece_sem_mudanca(svc, sample_workspace, sample_project):
    ws, dm = sample_workspace.id, sample_project.id
    a, act = svc.upsert(ws, dm, "regra/money", **FIELDS)
    assert act == "created" and a.key == "regra/money"
    b, act = svc.upsert(ws, dm, "regra/money", summary="Valores em Money (centavos)")
    assert act == "updated" and b.id == a.id and b.summary.endswith("(centavos)")
    _, act = svc.upsert(ws, dm, "regra/money", summary="Valores em Money (centavos)")
    assert act == "unchanged"


def test_upsert_grava_o_arquivo_no_caminho_da_key(svc, sample_workspace, sample_project,
                                                    data_dir):
    svc.upsert(sample_workspace.id, sample_project.id, "regra/money", **FIELDS)
    text = (data_dir / "testworkspace" / "testproject" / "regra" / "money.md").read_text(
        encoding="utf-8")
    assert "workspace: TestWorkspace" in text and "Use Money, nunca double." in text


def test_upsert_so_sobe_classe(svc, sample_workspace, sample_project):
    ws, dm = sample_workspace.id, sample_project.id
    svc.upsert(ws, dm, "k", **{**FIELDS, "memory_class": "longterm"})
    item, act = svc.upsert(ws, dm, "k", memory_class="working")
    assert item.memory_class == "longterm" and act == "unchanged"
    item, act = svc.upsert(ws, dm, "k", memory_class="canonical")
    assert item.memory_class == "canonical" and act == "updated"


def test_key_duplicada_no_create_falha(svc, sample_workspace, sample_project):
    kw = dict(workspace_id=sample_workspace.id, project_id=sample_project.id, key="dup", **FIELDS)
    svc.create(**kw)
    with pytest.raises(ValidationError, match="upsert"):
        svc.create(**kw)


def test_key_invalida(svc, sample_workspace, sample_project):
    with pytest.raises(ValidationError):
        svc.upsert(sample_workspace.id, sample_project.id, "Com Espaço", **FIELDS)


def test_lote_cria_local_e_atualiza_numa_publicacao(svc, data_dir):
    rows = svc.batch_upsert([
        {"workspace": "Polara", "project": "projpro", "key": "a", **FIELDS},
        {"workspace": "Polara", "project": "projpro", "key": "b", **FIELDS, "title": "Outra"},
    ])
    assert [r["action"] for r in rows] == ["created", "created"]
    rows = svc.batch_upsert([
        {"workspace": "Polara", "project": "projpro", "key": "a", "summary": "nova"},
        {"workspace": "Polara", "project": "projpro", "key": "c", **FIELDS},
    ])
    assert [r["action"] for r in rows] == ["updated", "created"]
    assert [w.name for w in WorkspaceService().list()] == ["Polara"]
    assert _md_files(data_dir) == ["polara/projpro/a.md", "polara/projpro/b.md",
                                   "polara/projpro/c.md"]


def test_lote_com_erro_nao_grava_nada(svc, data_dir):
    with pytest.raises(ValidationError, match="Entrada 1"):
        svc.batch_upsert([
            {"workspace": "W", "project": "D", "key": "ok", **FIELDS},
            {"workspace": "W", "project": "D", "key": "ruim", **FIELDS, "type": "inexistente"},
        ])
    assert _md_files(data_dir) == []


def test_similar_avisa_titulo_parecido(svc, sample_workspace, sample_project):
    svc.create(workspace_id=sample_workspace.id, project_id=sample_project.id, **FIELDS)
    found = svc.similar(sample_workspace.id, "pagamentos em Money")
    assert found and found[0]["title"] == FIELDS["title"]


def test_tags_e_labels_editaveis(svc, sample_workspace, sample_project):
    it = svc.create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                    tags=["a"], **FIELDS)
    it = svc.update(it.id, tags=["b", "c"], labels=["official"])
    assert it.tags == ["b", "c"]
    assert it.labels == ["official"]


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


def test_supersedes_marca_o_antigo(svc, sample_workspace, sample_project):
    ws, dm = sample_workspace.id, sample_project.id
    velho = svc.create(workspace_id=ws, project_id=dm, **{**FIELDS, "title": "Deploy manual"})
    novo = svc.create(workspace_id=ws, project_id=dm, **{**FIELDS, "title": "Deploy no CI"})
    RelationService().create(novo.id, velho.id, "supersedes")
    assert svc.get(velho.id).status == "superseded"
    assert [r["id"] for r in svc.search(ws, None, "deploy")] == [novo.id]


def test_renew_recalcula_expires_e_promote_limpa(svc, sample_workspace, sample_project):
    eph = svc.create(workspace_id=sample_workspace.id, project_id=sample_project.id,
                     **{**FIELDS, "memory_class": "ephemeral", "ttl_days": 1})
    mem = MemoryService()
    renewed = mem.renew(eph.id, 30)
    assert renewed.expires_at > eph.expires_at
    promoted = mem.promote(eph.id, "working")
    assert promoted.expires_at is None and promoted.ttl_days is None


def test_project_e_workspace_do_lote_reaproveitados(svc, sample_workspace, sample_project):
    svc.batch_upsert([{"workspace": sample_workspace.name, "project": sample_project.name,
                       "key": "x", **FIELDS}])
    assert [p.name for p in svc.brain().snapshot.projects(sample_workspace.id)] == [
        sample_project.name]


def test_nome_que_difere_so_na_caixa_cai_no_mesmo_workspace(svc, sample_workspace,
                                                            sample_project):
    svc.batch_upsert([{"workspace": "testworkspace", "project": "TESTPROJECT", "key": "x",
                       **FIELDS}])
    item = svc.get_by_key(sample_workspace.id, sample_project.id, "x")
    assert (item.workspace, item.project) == ("TestWorkspace", "TestProject")


def test_apagar_workspace_e_project_com_tags_relacoes_e_link(conn, data_dir):
    from knowledge_os.services.project_service import ProjectService
    from knowledge_os.services.repo_service import RepoService

    svc = ItemService()
    svc.batch_upsert([{"workspace": "W", "project": "D", "key": "a", **FIELDS, "tags": ["t"]}])
    svc.save([{"workspace": "W", "project": "D2", "key": "b", **FIELDS,
               "relations": [{"type": "related_to", "target": "b2"}]},
              {"workspace": "W", "project": "D2", "key": "b2", **FIELDS}])
    RepoService().link("github.com/o/r", "W", "D")
    assert ProjectService().delete("w", "D2") is True
    assert WorkspaceService().delete("W") is True
    assert _md_files(data_dir) == []
    assert RepoService().resolve("github.com/o/r") is None


def test_save_sem_memory_class_grava_longterm(svc, sample_workspace, sample_project):
    fields = {k: v for k, v in FIELDS.items() if k != "memory_class"}
    out = svc.save([{"key": "regra/sem-classe", **fields}],
                   default_location=(sample_workspace.id, sample_project.id))
    assert svc.get(out[0]["id"]).memory_class == "longterm"


def test_cada_lote_e_um_commit(svc, data_dir):
    import subprocess

    svc.save([{"workspace": "W", "project": "D", "key": "a", **FIELDS},
              {"workspace": "W", "project": "D", "key": "b", **FIELDS}])
    log = subprocess.run(["git", "log", "--oneline"], cwd=data_dir, capture_output=True,
                         text=True, check=True).stdout.splitlines()
    assert len(log) == 1 and "2 item(ns)" in log[0]
