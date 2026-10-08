"""Testes do serializador item <-> arquivo Markdown (services/item_file.py)."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.item_file import (
    item_path,
    parse_item_file,
    serialize_item,
    slugify,
)

# --------------------------------------------------------------------------- slugify


def test_slugify_minusculas_acento_espaco_e_caractere_especial():
    assert slugify("Pagamentos & Preços!") == "pagamentos-precos"


def test_slugify_colapsa_hifens_repetidos_e_tira_das_pontas():
    assert slugify("  --Money   em--- Pagamentos--  ") == "money-em-pagamentos"


def test_slugify_mantem_pontos_underscores_e_hifens():
    assert slugify("v1.2_beta-final") == "v1.2_beta-final"


# --------------------------------------------------------------------------- item_path


def test_item_path_com_key_simples():
    assert item_path("Polara", "app", "regra/money", "id-1") == "polara/app/regra/money.md"


def test_item_path_sem_key_usa_pasta_sem_key_e_o_id():
    assert item_path("Polara", "app", None, "id-1") == "polara/app/_sem-key/id-1.md"


def test_item_path_key_com_barra_vira_subpastas():
    # A key "regra/money" já contém "/"; o path final tem múltiplos níveis de pasta dentro
    # do project, não um nome de arquivo com "/" literal escapado.
    path = item_path("Polara", "App Beta", "regra/money", "id-1")
    assert path == "polara/app-beta/regra/money.md"
    assert path.count("/") == 3


# --------------------------------------------------------------------------- round-trip mínimo


def _minimal_item() -> dict:
    return {
        "id": "8f3e2c0a-0000-0000-0000-000000000001",
        "type": "rule",
        "title": "Money em pagamentos",
        "summary": "Valores em Money, nunca double",
        "content": "Nunca use float para dinheiro.",
        "status": "active",
        "key": None,
        "subtype": None,
        "scope": None,
        "links": [],
        "ttl_days": None,
        "keywords": None,
        "source": None,
        "origin": "agent",
        "verified_at": None,
        "verified_commit": None,
        "scope_paths": [],
        "created_at": datetime(2026, 10, 6, 12, 0, 0),
        "updated_at": datetime(2026, 10, 6, 12, 0, 0),
    }


def _serialize(item, subject=None, relations=(), tags=()) -> str:
    return serialize_item(item, workspace_name="Polara", project_name="app",
                          subject_name=subject, relations=list(relations), tags=list(tags))


def test_round_trip_minimo_sem_campos_opcionais():
    item = _minimal_item()
    raw = _serialize(item)
    parsed = parse_item_file(raw)

    assert parsed["id"] == item["id"]
    assert parsed["type"] == "rule" and parsed["subtype"] is None and parsed["scope"] is None
    assert parsed["title"] == "Money em pagamentos"
    assert parsed["summary"] == "Valores em Money, nunca double"
    assert parsed["status"] == "active"
    assert parsed["origin"] == "agent"
    assert parsed["key"] is None
    assert parsed["ttl_days"] is None
    assert parsed["keywords"] is None and parsed["source"] is None
    assert parsed["verified_at"] is None and parsed["verified_commit"] is None
    assert parsed["tags"] == [] and parsed["links"] == [] and parsed["scope_paths"] == []
    assert parsed["relations"] == []
    assert parsed["created_at"] == datetime(2026, 10, 6, 12, 0, 0)
    assert parsed["updated_at"] == datetime(2026, 10, 6, 12, 0, 0)
    assert parsed["content"] == "Nunca use float para dinheiro."

    for absent in ("access_count", "last_accessed", "expires_at", "key:", "subtype:",
                   "scope:", "ttl_days:", "keywords:", "source:", "subject:", "verified_at:",
                   "verified_commit:", "memory_class", "labels", "importance", "confidence"):
        assert absent not in raw


def test_origin_ausente_no_objeto_sai_agent():
    item = _minimal_item()
    del item["origin"]
    assert parse_item_file(_serialize(item))["origin"] == "agent"


# --------------------------------------------------------------------------- round-trip máximo


def _maximal_item() -> dict:
    return {
        **_minimal_item(),
        "id": "8f3e2c0a-0000-0000-0000-000000000002",
        "key": "rule/money-em-pagamentos",
        "subtype": "decision",
        "scope": "workspace",
        "content": "Nunca use float para dinheiro.\n\n## Por quê\nArredonda.",
        "links": [{"title": "ADR", "url": "https://x/adr"}],
        "ttl_days": 30,
        "keywords": "dinheiro, valores",
        "source": "PAY-142",
        "origin": "user",
        "verified_at": datetime(2026, 10, 7, 9, 0, 0),
        "verified_commit": "abc123",
        "scope_paths": ["src/payments/**"],
        "updated_at": datetime(2026, 10, 6, 13, 0, 0),
    }


def test_round_trip_maximo_com_todos_os_campos_opcionais():
    item = _maximal_item()
    raw = _serialize(item, subject="pagamentos",
                     relations=[{"type": "supersedes", "target": "howto/deploy"}],
                     tags=["pix", "dinheiro"])
    parsed = parse_item_file(raw)

    for name in ("key", "subtype", "scope", "links", "ttl_days", "keywords", "source", "origin",
                 "verified_at", "verified_commit", "scope_paths", "created_at", "updated_at",
                 "content"):
        assert parsed[name] == item[name], name
    assert parsed["tags"] == ["pix", "dinheiro"]
    assert parsed["subject"] == "pagamentos"
    assert parsed["relations"] == [{"type": "supersedes", "target": "howto/deploy"}]
    assert "expires_at:" not in raw and "access_count" not in raw


def test_ordem_dos_campos_no_frontmatter():
    raw = _serialize(_maximal_item(), subject="pagamentos",
                     relations=[{"type": "references", "target": "x"}], tags=["pix"])
    head = raw.split("---\n")[1]
    keys = [ln.split(":")[0] for ln in head.splitlines() if ln and not ln.startswith(" ")]
    assert keys == ["key", "id", "workspace", "project", "subject", "type", "subtype", "scope",
                    "title", "status", "tags", "links", "scope_paths", "ttl_days", "keywords",
                    "source", "origin", "verified_at", "verified_commit", "created_at",
                    "updated_at", "relations", "summary"]


def test_ida_e_volta_sem_perda():
    raw = _serialize(_maximal_item(), subject="pagamentos", tags=["pix"],
                     relations=[{"type": "depends_on", "target": "rule/x"}])
    parsed = parse_item_file(raw)
    again = serialize_item(parsed, workspace_name=parsed["workspace"],
                           project_name=parsed["project"], subject_name=parsed["subject"],
                           relations=parsed["relations"], tags=parsed["tags"])
    assert again == raw


def test_relation_alvo_por_id_quando_alvo_nao_tem_key():
    raw = _serialize(_minimal_item(),
                     relations=[{"type": "references", "target": "8f3e2c0a-target-sem-key"}])
    assert parse_item_file(raw)["relations"] == [
        {"type": "references", "target": "8f3e2c0a-target-sem-key"}
    ]


def test_serialize_aceita_objeto_com_atributos_alem_de_dict():
    orm_item = SimpleNamespace(
        id="orm-1", type="rule", subtype="pattern", title="Padrão X", summary="Resumo",
        content="Arquivo-modelo: x.py", status="active", key="rule/x",
        scope_paths=["src/x/**"], created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2),
    )
    parsed = parse_item_file(_serialize(orm_item, tags=["t1"]))
    assert parsed["id"] == "orm-1" and parsed["key"] == "rule/x"
    assert parsed["subtype"] == "pattern" and parsed["origin"] == "agent"
    assert parsed["scope_paths"] == ["src/x/**"] and parsed["tags"] == ["t1"]


# --------------------------------------------------------------------------- segredo


def test_serialize_aceita_item_secret_so_com_metadados():
    item = {**_minimal_item(), "type": "secret", "key": "secret/token"}
    parsed = parse_item_file(_serialize(item))
    assert parsed["type"] == "secret" and parsed["key"] == "secret/token"


@pytest.mark.parametrize("campo", ["value", "valor", "secret_value", "ciphertext"])
def test_serialize_recusa_secret_com_valor(campo):
    item = {**_minimal_item(), "type": "secret", campo: "s3nh4"}
    with pytest.raises(ValidationError, match="secret"):
        _serialize(item)


# --------------------------------------------------------------------------- arquivo antigo → v2


def _old_file(**over) -> str:
    fields = {
        "key": "gotcha/x", "id": "7390762d-0000", "workspace": "Global", "project": "Geral",
        "type": "rule", "title": "T", "status": "active", "memory_class": "longterm",
        "tags": "[]", "labels": "[]", "scope_paths": "[]", "keywords": None,
        "created_at": "'2026-10-05T18:01:54Z'", "updated_at": "'2026-10-05T18:01:54Z'",
        "relations": "[]", "summary": "S",
    }
    fields.update(over)
    lines = [f"{k}: {v}" for k, v in fields.items() if v is not None]
    return "---\n" + "\n".join(lines) + "\n---\nCorpo antigo.\n"


@pytest.mark.parametrize(
    ("old_type", "new_type", "subtype"),
    [("insight", "rule", "decision"), ("procedure", "howto", None),
     ("knowledge", "howto", "troubleshoot"), ("pattern", "rule", "pattern"),
     ("task", "spec", None)],
)
def test_arquivo_antigo_tipo_traduzido(old_type, new_type, subtype):
    parsed = parse_item_file(_old_file(type=old_type))
    assert parsed["type"] == new_type and parsed["subtype"] == subtype


def test_arquivo_antigo_knowledge_vira_review():
    assert parse_item_file(_old_file(type="knowledge"))["status"] == "review"


def test_arquivo_antigo_rule_sensivel_vira_security():
    parsed = parse_item_file(_old_file(keywords="tenant filtro sensivel"))
    assert parsed["subtype"] == "security" and parsed["keywords"] == "tenant filtro"


@pytest.mark.parametrize("status", ["superseded", "deprecated"])
def test_arquivo_antigo_status_vira_archived(status):
    assert parse_item_file(_old_file(status=status))["status"] == "archived"


def test_arquivo_antigo_labels_viram_tags_e_campos_saem():
    parsed = parse_item_file(_old_file(tags="[pix]", labels="[official]", importance=5,
                                       confidence=90))
    assert parsed["tags"] == ["pix", "official"]
    for gone in ("labels", "memory_class", "importance", "confidence"):
        assert gone not in parsed


def test_arquivo_antigo_ephemeral_mantem_ttl_e_outro_perde():
    assert parse_item_file(_old_file(memory_class="ephemeral", ttl_days=7))["ttl_days"] == 7
    assert parse_item_file(_old_file(memory_class="working", ttl_days=7))["ttl_days"] is None


def test_arquivo_antigo_origin_user():
    assert parse_item_file(_old_file())["origin"] == "user"


def test_arquivo_antigo_regravado_sai_v2_e_volta_igual():
    parsed = parse_item_file(_old_file(type="insight", labels="[official]", status="deprecated"))
    raw = serialize_item(parsed, workspace_name=parsed["workspace"],
                         project_name=parsed["project"], subject_name=parsed["subject"],
                         relations=parsed["relations"], tags=parsed["tags"])
    assert "memory_class" not in raw and "labels" not in raw
    again = parse_item_file(raw)
    assert again == parsed


# --------------------------------------------------------------------------- frontmatter malformado


def test_parse_sem_frontmatter_levanta_validation_error():
    with pytest.raises(ValidationError):
        parse_item_file("Só um texto qualquer, sem frontmatter.")


def test_parse_frontmatter_yaml_invalido_levanta_validation_error():
    with pytest.raises(ValidationError):
        parse_item_file("---\nkey: [sem fechar\n---\nconteudo\n")


@pytest.mark.parametrize(
    "campo", ["id", "type", "title", "summary", "status", "created_at", "updated_at"],
)
def test_parse_sem_campo_obrigatorio_levanta_validation_error(campo):
    raw = _serialize(_minimal_item())
    linhas = [linha for linha in raw.splitlines() if not linha.startswith(f"{campo}:")]
    with pytest.raises(ValidationError, match=campo):
        parse_item_file("\n".join(linhas))


# --------------------------------------------------------------------------- tipos inesperados


def _troca(raw: str, campo: str, valor: str) -> str:
    linhas = [ln for ln in raw.splitlines() if not ln.startswith(f"{campo}:")]
    linhas.insert(1, f"{campo}: {valor}")
    return "\n".join(linhas) + "\n"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("title", "2024"),
        ("summary", "[a, b]"),
        ("type", "{x: 1}"),
        ("type", "note"),
        ("subtype", "foo"),
        ("scope", "everywhere"),
        ("origin", "human"),
        ("status", "true"),
        ("status", "inventado"),
        ("id", "[a]"),
        ("workspace", "[x]"),
        ("project", "12"),
        ("subject", "{a: b}"),
        ("key", "[x]"),
        ("keywords", "[a]"),
        ("source", "{a: 1}"),
        ("verified_commit", "[a]"),
        ("verified_at", "ontem"),
        ("tags", "[1, x]"),
        ("tags", "texto"),
        ("links", "[x]"),
        ("links", "[{title: a}]"),
        ("scope_paths", "src/x"),
        ("relations", "[x]"),
        ("relations", "[{type: related_to}]"),
        ("relations", "[{type: 1, target: x}]"),
        ("relations", "{type: a, target: b}"),
        ("ttl_days", "sete"),
        ("created_at", "2024-01-01"),
        ("updated_at", "12"),
    ],
)
def test_parse_tipo_inesperado_levanta_validation_error(campo, valor):
    raw = _troca(_serialize(_minimal_item()), campo, valor)
    with pytest.raises(ValidationError, match=campo):
        parse_item_file(raw)


def test_parse_campos_opcionais_vazios_continuam_validos():
    raw = _serialize(_minimal_item())
    for campo in ("tags", "links", "scope_paths", "relations"):
        raw = _troca(raw, campo, "")
    parsed = parse_item_file(raw)
    assert parsed["tags"] == [] and parsed["links"] == [] and parsed["relations"] == []
