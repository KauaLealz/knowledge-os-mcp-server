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
        "memory_class": "longterm",
        "title": "Money em pagamentos",
        "summary": "Valores em Money, nunca double",
        "content": "Nunca use float para dinheiro.",
        "status": "active",
        "key": None,
        "confidence": None,
        "importance": None,
        "ttl_days": None,
        "keywords": None,
        "source": None,
        "scope_paths": [],
        "created_at": datetime(2026, 10, 6, 12, 0, 0),
        "updated_at": datetime(2026, 10, 6, 12, 0, 0),
    }


def test_round_trip_minimo_sem_campos_opcionais():
    item = _minimal_item()
    raw = serialize_item(
        item,
        workspace_name="Polara",
        project_name="app",
        subject_name=None,
        relations=[],
        tags=[],
        labels=[],
    )
    parsed = parse_item_file(raw)

    assert parsed["id"] == item["id"]
    assert parsed["type"] == "rule"
    assert parsed["title"] == "Money em pagamentos"
    assert parsed["summary"] == "Valores em Money, nunca double"
    assert parsed["status"] == "active"
    assert parsed["memory_class"] == "longterm"
    assert parsed["key"] is None
    assert parsed["confidence"] is None
    assert parsed["importance"] is None
    assert parsed["ttl_days"] is None
    assert parsed["keywords"] is None
    assert parsed["source"] is None
    assert parsed["tags"] == []
    assert parsed["labels"] == []
    assert parsed["scope_paths"] == []
    assert parsed["relations"] == []
    assert parsed["created_at"] == datetime(2026, 10, 6, 12, 0, 0)
    assert parsed["updated_at"] == datetime(2026, 10, 6, 12, 0, 0)
    assert parsed["content"] == "Nunca use float para dinheiro."

    # Campos de telemetria nunca aparecem no arquivo.
    assert "access_count" not in raw
    assert "last_accessed" not in raw
    assert "expires_at" not in raw

    # Campos opcionais ausentes não viram linhas "campo: null" no arquivo.
    assert "key:" not in raw
    assert "confidence:" not in raw
    assert "importance:" not in raw
    assert "ttl_days:" not in raw
    assert "keywords:" not in raw
    assert "source:" not in raw
    assert "subject:" not in raw


# --------------------------------------------------------------------------- round-trip máximo


def _maximal_item() -> dict:
    return {
        "id": "8f3e2c0a-0000-0000-0000-000000000002",
        "type": "rule",
        "memory_class": "ephemeral",
        "title": "Money em pagamentos",
        "summary": "Valores em Money, nunca double",
        "content": "Nunca use float para dinheiro.\n\nUse Money.",
        "status": "active",
        "key": "regra/money-em-pagamentos",
        "confidence": 90,
        "importance": 7,
        "ttl_days": 30,
        "keywords": "dinheiro, valores",
        "source": "PAY-142",
        "scope_paths": ["src/payments/**"],
        "created_at": datetime(2026, 10, 6, 12, 0, 0),
        "updated_at": datetime(2026, 10, 6, 13, 0, 0),
    }


def test_round_trip_maximo_com_todos_os_campos_opcionais():
    item = _maximal_item()
    raw = serialize_item(
        item,
        workspace_name="Polara",
        project_name="app",
        subject_name="pagamentos",
        relations=[{"type": "supersedes", "target": "proc/deploy"}],
        tags=["pix", "dinheiro"],
        labels=["official"],
    )
    parsed = parse_item_file(raw)

    assert parsed["key"] == "regra/money-em-pagamentos"
    assert parsed["memory_class"] == "ephemeral"
    assert parsed["confidence"] == 90
    assert isinstance(parsed["confidence"], int)
    assert parsed["importance"] == 7
    assert isinstance(parsed["importance"], int)
    assert parsed["ttl_days"] == 30
    assert isinstance(parsed["ttl_days"], int)
    assert parsed["keywords"] == "dinheiro, valores"
    assert parsed["source"] == "PAY-142"
    assert parsed["scope_paths"] == ["src/payments/**"]
    assert parsed["tags"] == ["pix", "dinheiro"]
    assert parsed["labels"] == ["official"]
    assert parsed["subject"] == "pagamentos"
    assert parsed["relations"] == [{"type": "supersedes", "target": "proc/deploy"}]
    assert parsed["created_at"] == datetime(2026, 10, 6, 12, 0, 0)
    assert parsed["updated_at"] == datetime(2026, 10, 6, 13, 0, 0)
    assert parsed["content"] == "Nunca use float para dinheiro.\n\nUse Money."

    # expires_at nunca é lido do arquivo (nunca persistido) — não deve estar no raw.
    assert "expires_at:" not in raw
    assert "access_count" not in raw
    assert "last_accessed" not in raw


def test_relation_alvo_por_id_quando_alvo_nao_tem_key():
    item = _minimal_item()
    raw = serialize_item(
        item,
        workspace_name="Polara",
        project_name="app",
        subject_name=None,
        relations=[{"type": "references", "target": "8f3e2c0a-target-sem-key"}],
        tags=[],
        labels=[],
    )
    parsed = parse_item_file(raw)
    assert parsed["relations"] == [{"type": "references", "target": "8f3e2c0a-target-sem-key"}]


# --------------------------------------------------------------------------- Item ORM


def test_serialize_aceita_objeto_com_atributos_alem_de_dict():
    orm_item = SimpleNamespace(
        id="orm-1",
        type="pattern",
        memory_class="longterm",
        title="Padrão X",
        summary="Resumo do padrão",
        content="Conteúdo do padrão.",
        status="active",
        key="padrao/x",
        scope_paths=["src/x/**"],
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        updated_at=datetime(2026, 1, 2, 0, 0, 0),
    )
    raw = serialize_item(
        orm_item,
        workspace_name="Polara",
        project_name="app",
        subject_name=None,
        relations=[],
        tags=["t1"],
        labels=[],
    )
    parsed = parse_item_file(raw)
    assert parsed["id"] == "orm-1"
    assert parsed["key"] == "padrao/x"
    assert parsed["scope_paths"] == ["src/x/**"]
    assert parsed["tags"] == ["t1"]


# --------------------------------------------------------------------------- segredo recusado


def test_serialize_aceita_item_secret_so_com_metadados():
    item = _minimal_item()
    item["type"] = "secret"
    item["key"] = "segredo/token"
    raw = serialize_item(
        item,
        workspace_name="Polara",
        project_name="app",
        subject_name=None,
        relations=[],
        tags=[],
        labels=[],
    )
    parsed = parse_item_file(raw)
    assert parsed["type"] == "secret" and parsed["key"] == "segredo/token"


@pytest.mark.parametrize("campo", ["value", "valor", "secret_value", "ciphertext"])
def test_serialize_recusa_secret_com_valor(campo):
    item = _minimal_item()
    item["type"] = "secret"
    item[campo] = "s3nh4"
    with pytest.raises(ValidationError, match="secret"):
        serialize_item(
            item,
            workspace_name="Polara",
            project_name="app",
            subject_name=None,
            relations=[],
            tags=[],
            labels=[],
        )


# --------------------------------------------------------------------------- frontmatter malformado


def test_parse_sem_frontmatter_levanta_validation_error():
    with pytest.raises(ValidationError):
        parse_item_file("Só um texto qualquer, sem frontmatter.")


def test_parse_frontmatter_yaml_invalido_levanta_validation_error():
    raw = "---\nkey: [sem fechar\n---\nconteudo\n"
    with pytest.raises(ValidationError):
        parse_item_file(raw)


@pytest.mark.parametrize(
    "campo",
    ["id", "type", "title", "summary", "status", "memory_class", "created_at", "updated_at"],
)
def test_parse_sem_campo_obrigatorio_levanta_validation_error(campo):
    item = _minimal_item()
    raw = serialize_item(
        item,
        workspace_name="Polara",
        project_name="app",
        subject_name=None,
        relations=[],
        tags=[],
        labels=[],
    )
    # Remove a linha do campo obrigatório do frontmatter.
    linhas = [linha for linha in raw.splitlines() if not linha.startswith(f"{campo}:")]
    raw_quebrado = "\n".join(linhas)
    with pytest.raises(ValidationError, match=campo):
        parse_item_file(raw_quebrado)


# --------------------------------------------------------------------------- tipos inesperados


def _raw_minimo() -> str:
    return serialize_item(
        _minimal_item(), workspace_name="Polara", project_name="app", subject_name=None,
        relations=[], tags=[], labels=[],
    )


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
        ("status", "true"),
        ("id", "[a]"),
        ("workspace", "[x]"),
        ("project", "12"),
        ("subject", "{a: b}"),
        ("key", "[x]"),
        ("keywords", "[a]"),
        ("source", "{a: 1}"),
        ("tags", "[1, x]"),
        ("tags", "texto"),
        ("labels", "[{a: b}]"),
        ("scope_paths", "src/x"),
        ("relations", "[x]"),
        ("relations", "[{type: related_to}]"),
        ("relations", "[{type: 1, target: x}]"),
        ("relations", "{type: a, target: b}"),
        ("confidence", "alto"),
        ("importance", "[1]"),
        ("ttl_days", "sete"),
        ("created_at", "2024-01-01"),
        ("updated_at", "12"),
    ],
)
def test_parse_tipo_inesperado_levanta_validation_error(campo, valor):
    raw = _troca(_raw_minimo(), campo, valor)
    with pytest.raises(ValidationError, match=campo):
        parse_item_file(raw)


def test_parse_campos_opcionais_vazios_continuam_validos():
    raw = _raw_minimo()
    for campo in ("tags", "labels", "scope_paths", "relations"):
        raw = _troca(raw, campo, "")
    parsed = parse_item_file(raw)
    assert parsed["tags"] == [] and parsed["relations"] == []
