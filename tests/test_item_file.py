"""Testes do serializador item <-> arquivo Markdown (services/item_file.py), formato v6."""

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
    path = item_path("Polara", "App Beta", "regra/money", "id-1")
    assert path == "polara/app-beta/regra/money.md"
    assert path.count("/") == 3


# --------------------------------------------------------------------------- round-trip


def _minimal_item() -> dict:
    return {
        "id": "8f3e2c0a-0000-0000-0000-000000000001",
        "type": "rule",
        "title": "Money em pagamentos",
        "summary": "Valores em Money, nunca double",
        "content": "Nunca use float para dinheiro.",
        "key": None,
        "created_at": datetime(2026, 10, 6, 12, 0, 0),
        "updated_at": datetime(2026, 10, 6, 12, 0, 0),
    }


def _serialize(item, subject=None, links=(), tags=()) -> str:
    return serialize_item(item, workspace_name="Polara", project_name="app",
                          subject_name=subject, links=list(links), tags=list(tags))


def test_round_trip_minimo_sem_campos_opcionais():
    item = _minimal_item()
    raw = _serialize(item)
    parsed = parse_item_file(raw)

    assert parsed["id"] == item["id"]
    assert parsed["type"] == "rule"
    assert parsed["title"] == "Money em pagamentos"
    assert parsed["summary"] == "Valores em Money, nunca double"
    assert parsed["key"] is None
    assert parsed["tags"] == [] and parsed["links"] == []
    assert parsed["created_at"] == datetime(2026, 10, 6, 12, 0, 0)
    assert parsed["content"] == "Nunca use float para dinheiro."

    for absent in ("access_count", "last_accessed", "expires_at", "key:", "subject:",
                   "subtype:", "scope:", "status:", "origin:", "ttl_days:", "keywords:",
                   "source:", "verified_at:", "relations:", "memory_class", "labels"):
        assert absent not in raw


def _maximal_item() -> dict:
    return {
        **_minimal_item(),
        "id": "8f3e2c0a-0000-0000-0000-000000000002",
        "key": "rule/money-em-pagamentos",
        "content": "Nunca use float para dinheiro.\n\n## Por quê\nArredonda.",
        "updated_at": datetime(2026, 10, 6, 13, 0, 0),
    }


_LINKS = [{"url": "https://x/adr", "title": "ADR"}, {"path": "src/payments/**"},
          {"item": "rule/x", "rel": "depends_on"}]


def test_round_trip_maximo_com_links_e_tags():
    item = _maximal_item()
    raw = _serialize(item, subject="pagamentos", links=_LINKS, tags=["pix", "dinheiro"])
    parsed = parse_item_file(raw)

    for name in ("key", "created_at", "updated_at", "content"):
        assert parsed[name] == item[name], name
    assert parsed["tags"] == ["pix", "dinheiro"]
    assert parsed["subject"] == "pagamentos"
    assert parsed["links"] == _LINKS
    assert "expires_at:" not in raw and "access_count" not in raw


def test_ordem_dos_campos_no_frontmatter():
    raw = _serialize(_maximal_item(), subject="pagamentos", links=_LINKS, tags=["pix"])
    head = raw.split("---\n")[1]
    keys = [ln.split(":")[0] for ln in head.splitlines() if ln and not ln.startswith(" ")]
    assert keys == ["key", "id", "workspace", "project", "subject", "type", "title", "tags",
                    "links", "created_at", "updated_at", "summary"]


def test_ida_e_volta_sem_perda():
    raw = _serialize(_maximal_item(), subject="pagamentos", tags=["pix"], links=_LINKS)
    parsed = parse_item_file(raw)
    again = serialize_item(parsed, workspace_name=parsed["workspace"],
                           project_name=parsed["project"], subject_name=parsed["subject"],
                           links=parsed["links"], tags=parsed["tags"])
    assert again == raw


def test_serialize_aceita_objeto_com_atributos_alem_de_dict():
    orm_item = SimpleNamespace(
        id="orm-1", type="rule", title="Padrão X", summary="Resumo",
        content="Arquivo-modelo: x.py", key="rule/x", created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2),
    )
    parsed = parse_item_file(_serialize(orm_item, tags=["t1"], links=[{"path": "src/x/**"}]))
    assert parsed["id"] == "orm-1" and parsed["key"] == "rule/x"
    assert parsed["tags"] == ["t1"] and parsed["links"] == [{"path": "src/x/**"}]


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


# --------------------------------------------------------------------------- datas com offset


def _with_date(value: str) -> str:
    raw = _serialize(_minimal_item())
    lines = [f"created_at: {value}" if ln.startswith("created_at:") else ln
             for ln in raw.split("\n")]
    return "\n".join(lines)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("'2020-01-01T00:00:00+00:00'", datetime(2020, 1, 1)),
     ("'2020-01-01T10:00:00+03:00'", datetime(2020, 1, 1, 7)),
     ("'2020-01-01T10:00:00-03:00'", datetime(2020, 1, 1, 13)),
     ("2020-01-01T10:00:00+03:00", datetime(2020, 1, 1, 7)),
     ("'2020-01-01T00:00:00Z'", datetime(2020, 1, 1)),
     ("2020-01-01T00:00:00Z", datetime(2020, 1, 1)),
     ("'2020-01-01T00:00:00'", datetime(2020, 1, 1)),
     ("2020-01-01", datetime(2020, 1, 1)),
     ("'2020-01-01'", datetime(2020, 1, 1))],
)
def test_data_com_offset_ou_so_data_vira_utc_naive(value, expected):
    parsed = parse_item_file(_with_date(value))
    assert parsed["created_at"] == expected and parsed["created_at"].tzinfo is None


@pytest.mark.parametrize("value", ["lixo", "'2020-13-45'", "'ontem'", "[1, 2]"])
def test_data_invalida_e_erro_do_arquivo(value):
    with pytest.raises(ValidationError, match="created_at"):
        parse_item_file(_with_date(value))


# --------------------------------------------------------------------------- erros de parse


def test_parse_sem_frontmatter_levanta_validation_error():
    with pytest.raises(ValidationError, match="frontmatter"):
        parse_item_file("só corpo, sem frontmatter")


def test_parse_frontmatter_yaml_invalido_levanta_validation_error():
    with pytest.raises(ValidationError):
        parse_item_file("---\n: : :\n---\ncorpo")


@pytest.mark.parametrize("campo", ["id", "type", "title", "summary", "created_at", "updated_at"])
def test_parse_sem_campo_obrigatorio_levanta_validation_error(campo):
    raw = _serialize(_minimal_item())
    linhas = [ln for ln in raw.split("\n") if not ln.startswith(f"{campo}:")]
    with pytest.raises(ValidationError):
        parse_item_file("\n".join(linhas))


def test_parse_tipo_fora_da_taxonomia_levanta_validation_error():
    raw = _serialize(_minimal_item()).replace("type: rule", "type: note")
    with pytest.raises(ValidationError, match="type"):
        parse_item_file(raw)


def test_parse_links_fora_do_formato_levanta_validation_error():
    raw = _serialize(_minimal_item()).replace("links: []", "links: {a: b}")
    with pytest.raises(ValidationError, match="links"):
        parse_item_file(raw)
