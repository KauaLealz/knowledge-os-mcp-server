"""`ItemService.save` no modelo v2 (V2_MVP.md §2, §6): validação, avisos, upsert, mover, lote
atômico, scope efetivo, ttl, origin e segredos."""

import subprocess

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.brain import Brain
from knowledge_os.services.item_service import ItemService

LOC = ("W", "P")
RULE = {"type": "rule", "title": "Money em pagamentos", "summary": "Valores sempre em Money",
        "content": "Use Money, nunca double."}


@pytest.fixture
def svc(conn) -> ItemService:
    return ItemService()


def _md_files(data_dir):
    return sorted(p.relative_to(data_dir).as_posix() for p in data_dir.rglob("*.md")
                  if ".git" not in p.parts)


def _git_log(data_dir):
    return subprocess.run(["git", "log", "--oneline"], cwd=data_dir, capture_output=True,
                          text=True, check=True).stdout.splitlines()


def _set_meta(rel, data):
    brain = Brain()
    with brain.editing() as d:
        d.set_meta(rel, data)
        brain.commit(d, "meta")


# ---- validação --------------------------------------------------------------------------


@pytest.mark.parametrize("entry, needle", [
    ({"type": "note"}, "Válidos: rule, howto, context, work, secret"),
])
def test_valor_invalido_lista_os_validos(svc, data_dir, entry, needle):
    with pytest.raises(ValidationError, match="Entrada 0") as exc:
        svc.save([{**RULE, "key": "rule/x", **entry}], default_location=LOC)
    assert needle in str(exc.value)
    assert _md_files(data_dir) == []


@pytest.mark.parametrize("field", ["labels", "memory_class", "relations", "level", "foo"])
def test_campo_desconhecido_e_erro_com_os_validos(svc, field):
    with pytest.raises(ValidationError) as exc:
        svc.save([{**RULE, "key": "rule/x", field: ["x"]}], default_location=LOC)
    msg = str(exc.value)
    assert f"desconhecido(s): {field}" in msg and "Válidos: key, id, type, title" in msg


def test_criar_sem_titulo_ou_resumo_diz_o_que_falta(svc):
    with pytest.raises(ValidationError, match="Entrada 0.*title"):
        svc.save([{"type": "rule", "key": "rule/x", "summary": "s"}], default_location=LOC)


def test_sem_local_pede_workspace_e_project(svc):
    with pytest.raises(ValidationError, match="workspace e project"):
        svc.save([{**RULE, "key": "rule/x"}])


def test_mais_de_20_entradas_e_erro(svc):
    entries = [{**RULE, "key": f"rule/r{i}"} for i in range(21)]
    with pytest.raises(ValidationError, match="no máximo 20"):
        svc.save(entries, default_location=LOC)


# ---- avisos -----------------------------------------------------------------------------


def test_avisos_de_key_e_tag_nova(svc):
    svc.save([{**RULE, "key": "rule/base", "tags": ["pagamentos"]}], default_location=LOC)
    (row,) = svc.save([{**RULE, "key": "regra/x", "tags": ["pagamento"]}],
                      default_location=LOC)
    text = " | ".join(row["warnings"])
    assert "fora do padrão rule/<nome>" in text
    assert "tag nova 'pagamento' criada; existe parecida: 'pagamentos'" in text


def test_item_no_padrao_nao_tem_aviso(svc):
    (row,) = svc.save([{**RULE, "key": "rule/money"}], default_location=LOC)
    assert row["warnings"] == []


# ---- upsert, unchanged, mover -----------------------------------------------------------


def test_upsert_por_key_nao_duplica_e_reconhece_sem_mudanca(svc, data_dir):
    (a,) = svc.save([{**RULE, "key": "rule/money"}], default_location=LOC)
    (b,) = svc.save([{"key": "rule/money", "summary": "Valores em Money (centavos)"}],
                    default_location=LOC)
    (c,) = svc.save([{"key": "rule/money", "summary": "Valores em Money (centavos)"}],
                    default_location=LOC)
    assert (a["action"], b["action"], c["action"]) == ("created", "updated", "unchanged")
    assert a["id"] == b["id"] == c["id"] and a["key"] == "rule/money"
    assert _md_files(data_dir) == ["w/p/rule/money.md"]
    assert svc.get(a["id"]).summary.endswith("(centavos)")


def test_atualizacao_parcial_mantem_o_tipo_do_item(svc):
    svc.save([{"key": "work/x", "type": "work", "title": "Plano", "summary": "s"}],
             default_location=LOC)
    (row,) = svc.save([{"key": "work/x", "tags": ["done"]}], default_location=LOC)
    item = svc.get(row["id"])
    assert (row["action"], item.type, item.tags) == ("updated", "work", ["done"])


def test_mover_por_id_mantem_id_e_tira_o_arquivo_antigo(svc, data_dir):
    (a,) = svc.save([{**RULE, "key": "rule/money"}], default_location=LOC)
    (b,) = svc.save([{"id": a["id"], "workspace": "E", "project": "Q"}])
    assert b["action"] == "updated" and b["id"] == a["id"]
    assert _md_files(data_dir) == ["e/q/rule/money.md"]
    item = svc.get(a["id"])
    assert (item.workspace, item.project) == ("E", "Q")


def test_mover_para_onde_a_key_ja_existe_e_erro(svc):
    (a,) = svc.save([{**RULE, "key": "rule/money"}], default_location=LOC)
    svc.save([{**RULE, "key": "rule/money"}], default_location=("E", "Q"))
    with pytest.raises(ValidationError, match="já existe item com key 'rule/money'"):
        svc.save([{"id": a["id"], "workspace": "E", "project": "Q"}])


def test_id_inexistente_aponta_a_entrada(svc):
    with pytest.raises(ValidationError, match="Entrada 0.*não encontrado"):
        svc.save([{"id": "nao-existe", "title": "x"}])


def test_key_de_item_existente_nao_muda(svc):
    (a,) = svc.save([{**RULE, "key": "rule/money"}], default_location=LOC)
    with pytest.raises(ValidationError, match="key de um item existente não muda"):
        svc.save([{"id": a["id"], "key": "rule/outra"}])
    assert svc.get(a["id"]).key == "rule/money"


def test_lote_atomico_desfaz_tudo_e_aponta_a_entrada(svc, data_dir):
    with pytest.raises(ValidationError, match="Entrada 1"):
        svc.save([{**RULE, "key": "rule/ok"}, {**RULE, "key": "rule/ruim", "type": "x"}],
                 default_location=LOC)
    assert _md_files(data_dir) == []


def test_cada_lote_e_um_commit(svc, data_dir):
    svc.save([{**RULE, "key": "rule/a"}, {**RULE, "key": "rule/b", "title": "Outra"}],
             default_location=LOC)
    log = _git_log(data_dir)
    assert len(log) == 1 and "2 item(ns)" in log[0]
    svc.save([{**RULE, "key": "rule/a"}], default_location=LOC)  # nada mudou: sem commit
    assert len(_git_log(data_dir)) == 1


def test_criar_sem_key_devolve_similares(svc):
    svc.save([{**RULE, "key": "rule/money"}], default_location=LOC)
    (row,) = svc.save([{**RULE, "title": "Pagamentos em Money"}], default_location=LOC)
    assert row["action"] == "created" and row["key"] is None
    assert [s["key"] for s in row["similar"]] == ["rule/money"]


# ---- tags e links -----------------------------------------------------------------------


def test_campos_vao_ao_arquivo(svc, data_dir):
    links = [{"url": "https://x.example", "title": "Painel"}, {"path": "infra/**"}]
    (row,) = svc.save([{"key": "context/env", "type": "context", "title": "Ambientes",
                        "summary": "s", "links": links, "tags": ["environment"]}],
                      default_location=LOC)
    text = (data_dir / "w" / "p" / "context" / "env.md").read_text(encoding="utf-8")
    assert "https://x.example" in text and "infra/**" in text
    assert "environment" in text and "origin:" not in text and "scope:" not in text


# ---- segredos ---------------------------------------------------------------------------


def test_segredo_sem_valor_no_arquivo_e_com_fill_url(svc, data_dir):
    (row,) = svc.save([{"key": "secret/npm-token", "type": "secret", "title": "Token do npm",
                        "summary": "publicar no npm"}], default_location=LOC)
    assert row["has_value"] is False
    assert row["fill_url"].startswith("http://127.0.0.1:8765/ui/#/c/teste/w/w/p/p/")
    assert row["fill_url"].endswith(f"/i/{row['id']}")
    text = (data_dir / "w" / "p" / "secret" / "npm-token.md").read_text(encoding="utf-8")
    assert "type: secret" in text and "publicar no npm" in text


@pytest.mark.parametrize("field", ["value", "valor", "Token"])
def test_valor_de_segredo_e_recusado_sem_eco(svc, field):
    with pytest.raises(ValidationError, match="não passa pelo agente") as exc:
        svc.save([{"key": "secret/x", "type": "secret", "title": "T", "summary": "s",
                   field: "npm_Zx81kQ2pL0aVb7Yt3Rw9Mn4C"}], default_location=LOC)
    assert "npm_Zx81kQ2pL0aVb7Yt3Rw9Mn4C" not in str(exc.value)


def test_segredo_em_item_comum_e_recusado_sem_eco(svc, data_dir):
    with pytest.raises(ValidationError, match="parece conter um segredo") as exc:
        svc.save([{**RULE, "key": "rule/x", "content": "password=SuperSecreta123"}],
                 default_location=LOC)
    assert "SuperSecreta123" not in str(exc.value)
    assert _md_files(data_dir) == []
