"""Testes da taxonomia e da validação de entradas (knowledge_os/model.py)."""

import pytest

from knowledge_os import model
from knowledge_os.exceptions import ValidationError


def _entry(**over) -> dict:
    base = dict(type="rule", title="Money em pagamentos", summary="Valores em Money.",
                content="Use Money.")
    base.update(over)
    return base


# --------------------------------------------------------------------------- tipo e subtipo


def test_tipo_invalido_recusado_listando_os_validos():
    with pytest.raises(ValidationError) as exc:
        model.validate_entry(_entry(type="note"))
    msg = str(exc.value)
    for valid in ("rule", "howto", "context", "spec", "secret"):
        assert valid in msg


def test_tipo_antigo_nao_e_alias_no_item_save():
    with pytest.raises(ValidationError, match="rule"):
        model.validate_entry(_entry(type="insight"))


def test_subtipo_invalido_recusado_listando_os_do_tipo():
    with pytest.raises(ValidationError) as exc:
        model.validate_entry(_entry(subtype="foo"))
    msg = str(exc.value)
    for valid in ("code", "pattern", "security", "business", "process", "decision"):
        assert valid in msg
    assert "troubleshoot" not in msg


def test_secret_nao_tem_subtipo():
    with pytest.raises(ValidationError, match="secret"):
        model.validate_entry(_entry(type="secret", subtype="code"))


def test_subtipo_valido_e_tipo_normalizado():
    clean, warnings = model.validate_entry(_entry(type=" Howto ", subtype="procedure"))
    assert clean["type"] == "howto" and clean["subtype"] == "procedure"
    assert warnings == []


def test_campo_desconhecido_lista_os_validos():
    with pytest.raises(ValidationError) as exc:
        model.validate_entry(_entry(memory_class="longterm"))
    msg = str(exc.value)
    assert "memory_class" in msg and "subtype" in msg and "scope" in msg


def test_item_fields_sem_campos_removidos():
    for gone in ("memory_class", "importance", "confidence", "labels", "relations", "level"):
        assert gone not in model.ITEM_FIELDS
    for new in ("subtype", "scope", "links", "origin", "ttl_days"):
        assert new in model.ITEM_FIELDS


def test_local_do_item_passa_sem_validacao_de_taxonomia():
    clean, _ = model.validate_entry(_entry(workspace="Polara", project="app", subject="pix"))
    assert (clean["workspace"], clean["project"], clean["subject"]) == ("Polara", "app", "pix")


# --------------------------------------------------------------------------- status


@pytest.mark.parametrize("status", ["active", "review", "archived"])
def test_status_comum_vale_em_todo_tipo(status):
    for item_type in model.TYPES:
        clean, _ = model.validate_entry(_entry(type=item_type, status=status))
        assert clean["status"] == status


@pytest.mark.parametrize("status", ["draft", "done"])
def test_draft_e_done_so_em_spec(status):
    clean, _ = model.validate_entry(_entry(type="spec", status=status))
    assert clean["status"] == status
    with pytest.raises(ValidationError) as exc:
        model.validate_entry(_entry(type="rule", status=status))
    assert "spec" in str(exc.value) and "active" in str(exc.value)


@pytest.mark.parametrize("status", ["expired", "superseded", "deprecated", "x"])
def test_status_invalido_ou_derivado_recusado(status):
    with pytest.raises(ValidationError, match="active"):
        model.validate_entry(_entry(status=status))


# --------------------------------------------------------------------------- scope e origin


def test_scope_invalido_lista_os_validos():
    with pytest.raises(ValidationError) as exc:
        model.validate_entry(_entry(scope="everywhere"))
    for valid in ("scoped", "workspace", "global"):
        assert valid in str(exc.value)


def test_origin_invalido_lista_os_validos():
    with pytest.raises(ValidationError) as exc:
        model.validate_entry(_entry(origin="human"))
    for valid in ("user", "code", "agent"):
        assert valid in str(exc.value)


def test_scope_e_origin_validos():
    clean, _ = model.validate_entry(_entry(scope="global", origin="user"))
    assert clean["scope"] == "global" and clean["origin"] == "user"
    assert model.DEFAULT_ORIGIN == "agent"


# --------------------------------------------------------------------------- outros campos


def test_links_no_formato_title_url():
    clean, _ = model.validate_entry(_entry(links=[{"title": "Doc", "url": "https://x"},
                                                  {"url": "https://y"}]))
    assert clean["links"] == [{"title": "Doc", "url": "https://x"},
                              {"title": "https://y", "url": "https://y"}]
    with pytest.raises(ValidationError, match="url"):
        model.validate_entry(_entry(links=["https://x"]))


def test_tags_normalizadas_em_kebab_case():
    clean, _ = model.validate_entry(_entry(tags=["Pagamentos PIX", "dinheiro", "dinheiro"]))
    assert clean["tags"] == ["pagamentos-pix", "dinheiro"]


@pytest.mark.parametrize("ttl", [0, -1, "7", True])
def test_ttl_days_inteiro_positivo(ttl):
    with pytest.raises(ValidationError, match="ttl_days"):
        model.validate_entry(_entry(ttl_days=ttl))


def test_titulo_vazio_recusado():
    with pytest.raises(ValidationError, match="title"):
        model.validate_entry(_entry(title="  "))


# --------------------------------------------------------------------------- modelo do content


def test_rule_decision_sem_secoes_avisa():
    _, warnings = model.validate_entry(_entry(subtype="decision", content="Escolhemos X."))
    text = " ".join(warnings)
    assert "## Por quê" in text and "## Alternativa descartada" in text


def test_rule_decision_completa_nao_avisa():
    content = "X.\n\n## Por quê\nPorque sim.\n\n## Alternativa descartada\nY."
    _, warnings = model.validate_entry(_entry(subtype="decision", content=content))
    assert warnings == []


def test_rule_pattern_sem_arquivo_modelo_avisa():
    _, warnings = model.validate_entry(_entry(subtype="pattern", content="Faça assim."))
    assert any("Arquivo-modelo:" in w for w in warnings)


def test_howto_troubleshoot_sem_sintoma_causa_solucao_avisa():
    _, warnings = model.validate_entry(_entry(type="howto", subtype="troubleshoot",
                                              content="## Sintoma\nquebra"))
    text = " ".join(warnings)
    assert "## Causa" in text and "## Solução" in text and "## Sintoma" not in text


def test_context_environment_sem_links_avisa():
    _, warnings = model.validate_entry(_entry(type="context", subtype="environment"))
    assert any("links" in w for w in warnings)
    _, warnings = model.validate_entry(_entry(type="context", subtype="environment",
                                              links=[{"title": "Painel", "url": "https://p"}]))
    assert warnings == []


# --------------------------------------------------------------------------- key


def test_key_no_padrao_nao_avisa():
    _, warnings = model.validate_entry(_entry(key="rule/money-em-pagamentos"))
    assert warnings == []


@pytest.mark.parametrize("key", ["regra/money", "rule/Money", "rule/money_x", "money"])
def test_key_fora_do_padrao_avisa(key):
    clean, warnings = model.validate_entry(_entry(key=key))
    assert clean["key"] == key
    assert any("rule/<nome>" in w for w in warnings)


def test_key_que_sairia_da_pasta_recusada():
    with pytest.raises(ValidationError, match="key"):
        model.validate_entry(_entry(key="../x"))


# --------------------------------------------------------------------------- taxonomia em markdown


def test_taxonomy_markdown_tem_tipos_subtipos_e_valores():
    md = model.taxonomy_markdown()
    for word in ("rule", "troubleshoot", "environment", "dream", "secret", "scoped",
                 "global", "supersedes", "outdated", "draft", "origin"):
        assert word in md
    assert "|" in md


# --------------------------------------------------------------------------- leitura antiga


def _old(**over) -> dict:
    base = dict(id="a", type="rule", title="T", summary="S", status="active",
                memory_class="longterm", tags=[], labels=[], keywords=None)
    base.update(over)
    return base


@pytest.mark.parametrize(
    ("old_type", "new_type", "subtype"),
    [("insight", "rule", "decision"), ("procedure", "howto", None),
     ("knowledge", "howto", "troubleshoot"), ("pattern", "rule", "pattern"),
     ("task", "spec", None), ("rule", "rule", None), ("context", "context", None)],
)
def test_traducao_de_tipo_antigo(old_type, new_type, subtype):
    out = model.translate_legacy(_old(type=old_type))
    assert out["type"] == new_type and out.get("subtype") == subtype


def test_knowledge_antigo_vira_review():
    assert model.translate_legacy(_old(type="knowledge"))["status"] == "review"
    assert model.translate_legacy(_old(type="knowledge", status="deprecated"))["status"] == \
        "archived"


def test_rule_sensivel_vira_security_e_palavra_sai():
    out = model.translate_legacy(_old(keywords="tenant filtro sensivel isolamento"))
    assert out["subtype"] == "security"
    assert out["keywords"] == "tenant filtro isolamento"


@pytest.mark.parametrize("status", ["superseded", "deprecated"])
def test_status_antigo_vira_archived(status):
    assert model.translate_legacy(_old(status=status))["status"] == "archived"


def test_labels_somam_as_tags_e_campos_antigos_saem():
    out = model.translate_legacy(_old(tags=["pix"], labels=["official", "pix"],
                                      importance=5, confidence=90))
    assert out["tags"] == ["pix", "official"]
    for gone in ("labels", "memory_class", "importance", "confidence"):
        assert gone not in out


def test_ttl_so_fica_no_ephemeral():
    assert model.translate_legacy(_old(memory_class="ephemeral", ttl_days=7))["ttl_days"] == 7
    assert "ttl_days" not in model.translate_legacy(_old(memory_class="working", ttl_days=7))


def test_origin_antigo_user_e_novo_agent():
    assert model.translate_legacy(_old())["origin"] == "user"
    novo = {k: v for k, v in _old().items() if k not in ("memory_class", "labels")}
    assert model.translate_legacy(novo)["origin"] == "agent"


def test_arquivo_v2_passa_intacto():
    v2 = dict(id="a", type="rule", subtype="security", title="T", summary="S",
              status="active", tags=["x"], origin="code", keywords="sensivel")
    assert model.translate_legacy(dict(v2)) == v2
