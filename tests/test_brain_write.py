"""Escrita do segundo cérebro: upsert, lote, similares, segredos, ciclo de vida (plumb-brain T4)."""

import pytest
from sqlalchemy import Engine, func, select

from knowledge_os.db.models import Domain, Item, Workspace
from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.memory_service import MemoryService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.services.secret_guard import find_secret

FIELDS = dict(type="rule", memory_class="working", title="Money em pagamentos",
              summary="Valores sempre em Money", content="Use Money, nunca double.")


@pytest.fixture
def svc(test_engine: Engine) -> ItemService:
    return ItemService(test_engine)


def test_upsert_cria_atualiza_e_reconhece_sem_mudanca(svc, sample_workspace, sample_domain):
    ws, dm = sample_workspace.id, sample_domain.id
    a, act = svc.upsert(ws, dm, "regra/money", **FIELDS)
    assert act == "created" and a.key == "regra/money"
    b, act = svc.upsert(ws, dm, "regra/money", summary="Valores em Money (centavos)")
    assert act == "updated" and b.id == a.id and b.summary.endswith("(centavos)")
    _, act = svc.upsert(ws, dm, "regra/money", summary="Valores em Money (centavos)")
    assert act == "unchanged"


def test_upsert_so_sobe_classe(svc, sample_workspace, sample_domain):
    ws, dm = sample_workspace.id, sample_domain.id
    svc.upsert(ws, dm, "k", **{**FIELDS, "memory_class": "longterm"})
    item, act = svc.upsert(ws, dm, "k", memory_class="working")
    assert item.memory_class == "longterm" and act == "unchanged"
    item, act = svc.upsert(ws, dm, "k", memory_class="canonical")
    assert item.memory_class == "canonical" and act == "updated"


def test_key_duplicada_no_create_falha(svc, sample_workspace, sample_domain):
    kw = dict(workspace_id=sample_workspace.id, domain_id=sample_domain.id, key="dup", **FIELDS)
    svc.create(**kw)
    with pytest.raises(ValidationError, match="upsert"):
        svc.create(**kw)


def test_key_invalida(svc, sample_workspace, sample_domain):
    with pytest.raises(ValidationError):
        svc.upsert(sample_workspace.id, sample_domain.id, "Com Espaço", **FIELDS)


def test_lote_cria_local_e_atualiza_numa_transacao(svc, test_session, sample_workspace):
    rows = svc.batch_upsert([
        {"workspace": "Polara", "domain": "projpro", "key": "a", **FIELDS},
        {"workspace": "Polara", "domain": "projpro", "key": "b", **FIELDS, "title": "Outra"},
    ])
    assert [r["action"] for r in rows] == ["created", "created"]
    rows = svc.batch_upsert([
        {"workspace": "Polara", "domain": "projpro", "key": "a", "summary": "nova"},
        {"workspace": "Polara", "domain": "projpro", "key": "c", **FIELDS},
    ])
    assert [r["action"] for r in rows] == ["updated", "created"]
    assert test_session.scalar(select(func.count()).select_from(Workspace)
                               .where(Workspace.name == "Polara")) == 1


def test_lote_com_erro_nao_grava_nada(svc, test_session):
    with pytest.raises(ValidationError, match="Entrada 1"):
        svc.batch_upsert([
            {"workspace": "W", "domain": "D", "key": "ok", **FIELDS},
            {"workspace": "W", "domain": "D", "key": "ruim", **FIELDS, "type": "inexistente"},
        ])
    assert test_session.scalar(select(func.count()).select_from(Item)) == 0


def test_similar_avisa_titulo_parecido(svc, sample_workspace, sample_domain):
    svc.create(workspace_id=sample_workspace.id, domain_id=sample_domain.id, **FIELDS)
    found = svc.similar(sample_workspace.id, "pagamentos em Money")
    assert found and found[0]["title"] == FIELDS["title"]


def test_tags_e_labels_editaveis(svc, sample_workspace, sample_domain):
    it = svc.create(workspace_id=sample_workspace.id, domain_id=sample_domain.id,
                    tags=["a"], **FIELDS)
    it = svc.update(it.id, tags=["b", "c"], labels=["official"])
    assert sorted(t.name for t in it.tags) == ["b", "c"]
    assert [lb.name for lb in it.labels] == ["official"]


@pytest.mark.parametrize("texto", [
    "use AKIAABCDEFGHIJKLMNOP no deploy",
    "-----BEGIN RSA PRIVATE KEY-----",
    "token ghp_" + "a" * 36,
    "password=SuperSecreta123",
    "postgresql://user:minhasenha@db/x",
])
def test_segredo_bloqueado_sem_eco(svc, sample_workspace, sample_domain, texto):
    with pytest.raises(ValidationError) as exc:
        svc.create(workspace_id=sample_workspace.id, domain_id=sample_domain.id,
                   **{**FIELDS, "content": texto})
    assert "segredo" in str(exc.value)
    assert texto not in str(exc.value)


@pytest.mark.parametrize("texto", [
    "password=<sua-senha>", "senha: ${DB_PASSWORD}", "postgresql://user:***@db/x",
    "a senha fica no cofre", "api_key no .env.example",
])
def test_placeholder_nao_e_segredo(texto):
    assert find_secret(texto) is None


def test_supersedes_marca_o_antigo(svc, test_session, sample_workspace, sample_domain):
    ws, dm = sample_workspace.id, sample_domain.id
    velho = svc.create(workspace_id=ws, domain_id=dm, **{**FIELDS, "title": "Deploy manual"})
    novo = svc.create(workspace_id=ws, domain_id=dm, **{**FIELDS, "title": "Deploy no CI"})
    RelationService(session=test_session).create(novo.id, velho.id, "supersedes")
    assert svc.get(velho.id).status == "superseded"
    assert [r["id"] for r in svc.search(ws, None, "deploy")] == [novo.id]


def test_renew_recalcula_expires_e_promote_limpa(svc, test_session, sample_workspace,
                                                sample_domain):
    eph = svc.create(workspace_id=sample_workspace.id, domain_id=sample_domain.id,
                     **{**FIELDS, "memory_class": "ephemeral", "ttl_days": 1})
    mem = MemoryService(session=test_session)
    renewed = mem.renew(eph.id, 30)
    assert renewed.expires_at > eph.expires_at
    promoted = mem.promote(eph.id, "working")
    assert promoted.expires_at is None and promoted.ttl_days is None


def test_domain_e_workspace_do_lote_reaproveitados(svc, test_session, sample_workspace,
                                                  sample_domain):
    svc.batch_upsert([{"workspace": sample_workspace.name, "domain": sample_domain.name,
                       "key": "x", **FIELDS}])
    assert test_session.scalar(select(func.count()).select_from(Domain)) == 1


def test_apagar_workspace_e_domain_com_tags_relacoes_e_link(test_engine, test_session):
    """Regressão: com foreign_keys=ON, o delete falhava se os itens tinham tags ou relações."""
    from knowledge_os.services.domain_service import DomainService
    from knowledge_os.services.project_service import ProjectService
    from knowledge_os.services.workspace_service import WorkspaceService

    svc = ItemService(test_engine)
    svc.batch_upsert([{"workspace": "W", "domain": "D", "key": "a", **FIELDS, "tags": ["t"]}])
    svc.save([{"workspace": "W", "domain": "D2", "key": "b", **FIELDS,
               "relations": [{"type": "related_to", "target": "b2"}]},
              {"workspace": "W", "domain": "D2", "key": "b2", **FIELDS}])
    ProjectService(test_engine).link("github.com/o/r", "W", "D")
    ws_id = test_session.scalar(select(Workspace.id).where(Workspace.name == "W"))
    assert DomainService(session=test_session).delete(ws_id, "D2") is True
    assert WorkspaceService(session=test_session).delete("W") is True
    assert test_session.scalar(select(func.count()).select_from(Item)) == 0
