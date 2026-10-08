"""Serializador item <-> arquivo Markdown com frontmatter YAML.

Peça base da migração de storage (SQLite -> Git): transforma um `Item` (+ metadados de
workspace/project/subject) num arquivo `.md` com frontmatter YAML, e faz o caminho inverso.

Decisão de design: `serialize_item` aceita tanto um `Item` do SQLAlchemy quanto um `dict` com
os mesmos campos (chaves iguais aos atributos do modelo; `scope_paths` já decodificado como
lista em ambos os casos — ver `_field`/`_scope_paths`). Isso deixa o módulo testável sem sessão
de banco e sem acoplar quem só tem os dados em dict (ex.: payload vindo do Git) a uma instância
ORM. `tags`, `labels` e `relations` são sempre parâmetros à parte: no ORM eles são relações
carregadas separadamente, e `relations` já chega resolvido (pela key do alvo quando ele tem
uma, senão pelo id) — este módulo não decide essa resolução, só serializa o que recebe.

Segredos (`type == "secret"`) entram no arquivo só com metadados (título, resumo, key...): o
valor vive à parte, fora do git. `serialize_item` recusa com `ValidationError` um item secret que
traga algum campo de valor (`_SECRET_VALUE_FIELDS`).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

import yaml

from knowledge_os.exceptions import ValidationError
from knowledge_os.schemas.item_schemas import decode_paths

_SEM_KEY_DIR = "_sem-key"

# Campos obrigatórios no frontmatter: sem eles não dá para reconstruir o item.
_REQUIRED_FIELDS = (
    "id",
    "type",
    "title",
    "summary",
    "status",
    "memory_class",
    "created_at",
    "updated_at",
)

# Campos que carregariam o valor de um segredo: nunca podem chegar ao arquivo versionável.
_SECRET_VALUE_FIELDS = ("value", "valor", "secret_value", "ciphertext")

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n(.*)\Z", re.DOTALL)


class _IndentingDumper(yaml.SafeDumper):
    """SafeDumper que indenta itens de lista sob a chave-mãe (estilo usado no projeto)."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


# --------------------------------------------------------------------------- slugify / paths


def slugify(name: str) -> str:
    """Normaliza um nome para um segmento de path seguro.

    Minúsculas, sem acento, espaços e qualquer caractere fora de [a-z0-9._-] viram "-";
    hífens repetidos colapsam; hífens nas pontas são removidos.

    Não resolve colisão entre nomes diferentes que colapsam no mesmo slug (ex.: "App!" e
    "App?") — isso é responsabilidade de quem monta o path final, se precisar.
    """
    normalized = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    lowered = without_accents.lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def item_path(workspace_name: str, project_name: str, key: str | None, item_id: str) -> str:
    """Path do arquivo do item, relativo à raiz do repositório de dados.

    Com key: "<workspace-slug>/<project-slug>/<key>.md" — a key já usa "/" como separador de
    namespace (ex.: "regra/money"), que vira níveis de pasta dentro do project, não um nome de
    arquivo com "/" literal. Sem key (item criado só com título): o arquivo vai para a pasta
    "_sem-key", nomeado pelo id.
    """
    ws = slugify(workspace_name)
    dm = slugify(project_name)
    if key:
        return f"{ws}/{dm}/{key}.md"
    return f"{ws}/{dm}/{_SEM_KEY_DIR}/{item_id}.md"


# --------------------------------------------------------------------------- helpers de campo


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _scope_paths(item: Any) -> list[str]:
    if isinstance(item, dict):
        return list(item.get("scope_paths") or [])
    return decode_paths(item.scope_paths)


def _fmt_dt(value: datetime) -> str:
    """Formata um datetime (naive ou aware, assumido UTC) como "YYYY-MM-DDTHH:MM:SSZ"."""
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat() + "Z"


def _parse_dt(raw: Any, field: str) -> datetime:
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    if not isinstance(raw, str) or not raw:
        raise ValidationError(f"Frontmatter com {field!r} inválido ou ausente: {raw!r}")
    text = raw[:-1] if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"Frontmatter com {field!r} em formato inválido: {raw!r}") from exc


# --------------------------------------------------------------------------- serialize


def serialize_item(
    item: Any,
    *,
    workspace_name: str,
    project_name: str,
    subject_name: str | None,
    relations: list[dict[str, str]],
    tags: list[str],
    labels: list[str],
) -> str:
    """Serializa um item (Item do SQLAlchemy ou dict equivalente) em conteúdo de arquivo
    Markdown com frontmatter YAML.

    Item `type == "secret"` é serializado só com metadados; recusa (`ValidationError`) se ele
    trouxer algum campo de valor — o valor do segredo nunca vai pro git. Campos de telemetria
    (`access_count`, `last_accessed`) e `expires_at` (sempre recalculado a partir de
    `updated_at` + `ttl_days`) nunca são persistidos no arquivo.
    """
    item_type = _field(item, "type")
    if item_type == "secret":
        found = [f for f in _SECRET_VALUE_FIELDS if _field(item, f) is not None]
        if found:
            raise ValidationError(
                f"Item do tipo 'secret' com campo de valor ({', '.join(found)}) não pode ser "
                "serializado para arquivo versionável (o valor nunca vai para o git)"
            )

    memory_class = _field(item, "memory_class")
    key = _field(item, "key")

    data: dict[str, Any] = {}
    if key:
        data["key"] = key
    data["id"] = _field(item, "id")
    data["workspace"] = workspace_name
    data["project"] = project_name
    if subject_name:
        data["subject"] = subject_name
    data["type"] = item_type
    data["title"] = _field(item, "title")
    data["status"] = _field(item, "status")
    data["memory_class"] = memory_class
    data["tags"] = list(tags)
    data["labels"] = list(labels)
    data["scope_paths"] = _scope_paths(item)

    confidence = _field(item, "confidence")
    if confidence is not None:
        data["confidence"] = confidence
    importance = _field(item, "importance")
    if importance is not None:
        data["importance"] = importance
    if memory_class == "ephemeral":
        data["ttl_days"] = _field(item, "ttl_days")

    keywords = _field(item, "keywords")
    if keywords:
        data["keywords"] = keywords
    source = _field(item, "source")
    if source:
        data["source"] = source

    data["created_at"] = _fmt_dt(_field(item, "created_at"))
    data["updated_at"] = _fmt_dt(_field(item, "updated_at"))

    data["relations"] = [{"type": r["type"], "target": r["target"]} for r in relations]
    data["summary"] = _field(item, "summary")

    frontmatter = yaml.dump(
        data,
        Dumper=_IndentingDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    content = _field(item, "content") or ""
    return f"---\n{frontmatter}---\n{content}"


# --------------------------------------------------------------------------- parse


def parse_item_file(raw: str) -> dict[str, Any]:
    """Faz o caminho inverso de `serialize_item`: devolve um dict com os campos do
    frontmatter (tipados) mais `content` (o corpo do arquivo).

    Levanta `ValidationError` se o frontmatter estiver ausente, malformado, ou faltar algum
    campo obrigatório (`id`, `type`, `title`, `summary`, `status`, `memory_class`,
    `created_at`, `updated_at`).
    """
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        raise ValidationError("Arquivo sem frontmatter YAML (esperado '---' no início)")
    raw_frontmatter, content = match.groups()

    try:
        data = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError as exc:
        raise ValidationError(f"Frontmatter YAML malformado: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("Frontmatter YAML malformado: esperado um mapeamento no topo")

    missing = [f for f in _REQUIRED_FIELDS if data.get(f) is None]
    if missing:
        raise ValidationError(f"Frontmatter sem campo(s) obrigatório(s): {', '.join(missing)}")

    parsed: dict[str, Any] = {
        "id": data["id"],
        "key": data.get("key"),
        "workspace": data.get("workspace"),
        "project": data.get("project"),
        "subject": data.get("subject"),
        "type": data["type"],
        "title": data["title"],
        "status": data["status"],
        "memory_class": data["memory_class"],
        "tags": list(data.get("tags") or []),
        "labels": list(data.get("labels") or []),
        "scope_paths": list(data.get("scope_paths") or []),
        "confidence": data.get("confidence"),
        "importance": data.get("importance"),
        "ttl_days": data.get("ttl_days"),
        "keywords": data.get("keywords"),
        "source": data.get("source"),
        "created_at": _parse_dt(data["created_at"], "created_at"),
        "updated_at": _parse_dt(data["updated_at"], "updated_at"),
        "relations": list(data.get("relations") or []),
        "summary": data["summary"],
        "content": content,
    }
    return parsed
