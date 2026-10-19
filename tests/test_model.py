"""Modelo v6: taxonomia enxuta (5 tipos, sem subtipo/scope/status/origin/ttl), tags livres com
base, links unificados, validação mínima."""

from __future__ import annotations

import pytest

from knowledge_os import model
from knowledge_os.exceptions import ValidationError

# --------------------------------------------------------------------------- taxonomia

def test_cinco_tipos_sem_spec_legado():
    assert model.TYPES == ("rule", "howto", "context", "work", "secret")
    assert "spec" not in model.TYPES  # virou `work`


def test_tags_de_base():
    assert model.LIFECYCLE_TAGS == ("draft", "active", "done", "archived")
    for t in ("decision", "troubleshoot", "security"):
        assert t in model.NUANCE_TAGS
    assert set(model.BASE_TAGS) == set(model.LIFECYCLE_TAGS) | set(model.NUANCE_TAGS)


def test_campos_do_item_sao_minimos():
    assert model.ITEM_FIELDS == ("key", "id", "type", "title", "summary", "content", "tags",
                                 "links")
    for gone in ("subtype", "scope", "status", "origin", "ttl_days", "keywords", "source"):
        assert gone not in model.ITEM_FIELDS


def test_relacoes_de_link_sao_duas():
    assert model.LINK_RELATIONS == ("depends_on", "relates_to")
    assert "supersedes" not in model.LINK_RELATIONS


# --------------------------------------------------------------------------- key e tag

def test_key_valida_e_invalida():
    assert model.key_problem("rule/money") is None
    assert model.key_problem("") is not None
    assert model.key_problem("rule/../x") is not None
    assert model.key_problem("con") is not None  # nome reservado do Windows


def test_key_warning_fora_do_padrao():
    assert model.key_warnings("rule/money", "rule") == []
    assert model.key_warnings("Money", "rule")  # fora de <tipo>/<nome>


def test_normalize_tag():
    assert model.normalize_tag("Pagamentos Pix") == "pagamentos-pix"
    assert model.normalize_tag("Decisão") == "decisao"
    with pytest.raises(ValidationError):
        model.normalize_tag("!!!")


# --------------------------------------------------------------------------- links

def test_link_para_item():
    out = model.check_links([{"item": "rule/money", "rel": "depends_on"}])
    assert out == [{"item": "rule/money", "rel": "depends_on"}]


def test_link_rel_invalida():
    with pytest.raises(ValidationError):
        model.check_links([{"item": "rule/money", "rel": "supersedes"}])


def test_link_url_e_titulo():
    out = model.check_links([{"url": "https://painel.exemplo.com", "title": "Painel"}])
    assert out == [{"url": "https://painel.exemplo.com", "title": "Painel"}]


def test_link_url_esquema_proibido():
    with pytest.raises(ValidationError):
        model.check_links([{"url": "javascript:alert(1)"}])


def test_link_path_glob():
    out = model.check_links([{"path": "src/payments/**"}])
    assert out == [{"path": "src/payments/**"}]


def test_link_path_curingas_demais():
    with pytest.raises(ValidationError):
        model.check_links([{"path": "*/*/*/*/*/*/*/*/*/*"}])


def test_link_formato_desconhecido():
    with pytest.raises(ValidationError):
        model.check_links([{"foo": "bar"}])


# --------------------------------------------------------------------------- validate_entry

def test_validate_entry_minimo_ok():
    clean, warnings = model.validate_entry({
        "key": "rule/money", "type": "rule", "title": "Money", "summary": "Valores em centavos",
        "content": "...", "tags": ["Pagamentos", "decision"], "links": [{"path": "src/pay/**"}],
    })
    assert clean["type"] == "rule"
    assert clean["tags"] == ["pagamentos", "decision"]
    assert clean["links"] == [{"path": "src/pay/**"}]
    assert warnings == []


def test_validate_entry_rejeita_campo_antigo():
    for gone in ("subtype", "scope", "status", "origin", "ttl_days", "keywords", "source"):
        with pytest.raises(ValidationError):
            model.validate_entry({"type": "rule", gone: "x"})


def test_validate_entry_tipo_invalido():
    with pytest.raises(ValidationError):
        model.validate_entry({"type": "spec"})  # spec não existe mais


def test_validate_entry_title_vazio():
    with pytest.raises(ValidationError):
        model.validate_entry({"type": "rule", "title": "  "})


def test_validate_entry_location_passa():
    clean, _ = model.validate_entry({"type": "rule", "workspace": "Banco", "project": "ordens",
                                     "subject": "credito-privado"})
    assert clean["workspace"] == "Banco"
    assert clean["subject"] == "credito-privado"


# --------------------------------------------------------------------------- instruções

def test_taxonomy_markdown_reflete_v6():
    md = model.taxonomy_markdown()
    assert "`work`" in md and "`rule`" in md
    assert "scope" in md  # menciona que NÃO há scope
    for t in model.LIFECYCLE_TAGS:
        assert f"`{t}`" in md
