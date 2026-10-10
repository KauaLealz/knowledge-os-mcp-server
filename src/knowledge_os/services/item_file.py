"""Serializador item <-> arquivo Markdown com frontmatter YAML.

Cada item do segundo cérebro é um arquivo `.md` (frontmatter YAML + corpo) na pasta da conexão,
com os nomes de workspace/project/subject no frontmatter. `serialize_item` faz o arquivo e
`parse_item_file` faz o caminho inverso.

Formato v2 (taxonomia em `knowledge_os.model`): `subtype`, `scope`, `links`, `origin`,
`verified_at` e `verified_commit`; `memory_class`, `importance`, `confidence` e `labels` saíram.
Arquivo antigo continua legível: `parse_item_file` traduz na leitura (`model.translate_legacy`).

`serialize_item` aceita um `dict` ou qualquer objeto com os mesmos campos (`scope_paths` e
`links` como lista). `tags` e `relations` são sempre parâmetros à parte, e `relations` já chega
resolvido (pela key do alvo quando ele tem uma no mesmo project, senão pelo id) — este módulo
não decide essa resolução, só serializa o que recebe.

Segredos (`type == "secret"`) entram no arquivo só com metadados (título, resumo, key...): o
valor vive à parte, fora do git. `serialize_item` recusa com `ValidationError` um item secret que
traga algum campo de valor (`_SECRET_VALUE_FIELDS`).
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from knowledge_os.exceptions import ValidationError
from knowledge_os.model import (
    DEFAULT_ORIGIN,
    ORIGINS,
    SCOPES,
    SPEC_STATUSES,
    STATUSES,
    TYPES,
    key_problem,  # mora em `model`; segue importável daqui
    segment_problem,
    short_repr,
    translate_legacy,
)

# Teto do caminho completo (raiz da conexão + relativo) no Windows: o limite clássico é 260;
# 240 deixa folga para o temporário da escrita atômica (`.<nome>.<sorteio>.tmp`). `None` fora do
# Windows. Um caminho acima disso é recusado antes de qualquer escrita do lote.
MAX_PATH_CHARS: int | None = 240 if os.name == "nt" else None
MAX_REL_PATH_CHARS = 1000  # relativo à raiz, em qualquer sistema

_SEM_KEY_DIR = "_sem-key"
_s = short_repr  # valor citado em mensagem de erro: sempre cortado

# Loader seguro em C quando o PyYAML foi compilado com libyaml: abrir milhares de itens com o
# loader em Python puro leva segundos.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

# Campos obrigatórios no frontmatter: sem eles não dá para reconstruir o item.
_REQUIRED_FIELDS = (
    "id",
    "type",
    "title",
    "summary",
    "status",
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


_ID_RE = re.compile(r"[A-Za-z0-9-]{1,100}")


def id_problem(item_id: Any) -> str | None:
    """Motivo pelo qual o id não serve (None se serve): só letras, números e hífen."""
    if not isinstance(item_id, str) or not _ID_RE.fullmatch(item_id):
        return f"id inválido: {_s(item_id)} (use só letras, números e '-')"
    return None


def folder_problem(name: Any, what: str) -> str | None:
    """Motivo pelo qual o nome de workspace/project não vira uma pasta segura (None se vira)."""
    if not isinstance(name, str):
        return f"{what} deve ser texto: {_s(name)}"
    slug = slugify(name)
    if not slug or slug.startswith(".") or slug in (".", ".."):
        return f"{what} inválido para nome de pasta: {_s(name)}"
    return None


def portable_folder_problem(name: Any, what: str) -> str | None:
    """`folder_problem` + o que o Windows não guarda no slug (ponto final, nome reservado):
    vale para toda gravação; a leitura de um arquivo existente usa só `folder_problem`."""
    return folder_problem(name, what) or segment_problem(slugify(name), what)


def path_length_problem(root: Path | None, rel: str) -> str | None:
    """Motivo pelo qual o caminho é longo demais para gravar (None se cabe)."""
    if len(rel) > MAX_REL_PATH_CHARS:
        return (f"caminho longo demais ({len(rel)} caracteres, máximo {MAX_REL_PATH_CHARS}): "
                f"{_s(rel)}; encurte o nome do workspace/project ou a key")
    if root is not None and MAX_PATH_CHARS:
        full = len(str(Path(root).resolve() / rel))
        if full > MAX_PATH_CHARS:
            return (f"caminho longo demais para o Windows ({full} caracteres, máximo "
                    f"{MAX_PATH_CHARS}): {_s(rel)}; encurte o nome do workspace/project "
                    "ou a key")
    return None


def safe_join(root: Path, rel: str) -> Path:
    """`root / rel`, desde que o destino (resolvido, seguindo symlink) fique dentro de `root`.

    Última barreira de toda gravação e remoção na pasta da conexão: um path relativo vindo de
    key, id ou nome que escape da pasta (ex.: "../../x", absoluto, ou por um symlink que aponta
    para fora) levanta `ValidationError` em vez de tocar o disco. Caminho longo demais para o
    sistema (`MAX_PATH_CHARS`, no Windows) também: quem grava confere o lote inteiro aqui antes
    da primeira escrita.
    """
    base = Path(root).resolve()
    target = Path(root) / rel
    if not target.resolve().is_relative_to(base) or target.resolve() == base:
        raise ValidationError(f"Caminho fora da pasta da conexão: {_s(rel)}")
    problem = path_length_problem(root, rel)
    if problem:
        raise ValidationError(problem)
    return target


def item_path(workspace_name: str, project_name: str, key: str | None, item_id: str) -> str:
    """Path do arquivo do item, relativo à raiz do repositório de dados.

    Com key: "<workspace-slug>/<project-slug>/<key>.md" — a key já usa "/" como separador de
    namespace (ex.: "regra/money"), que vira níveis de pasta dentro do project, não um nome de
    arquivo com "/" literal. Sem key (item criado só com título): o arquivo vai para a pasta
    "_sem-key", nomeado pelo id.

    Levanta `ValidationError` se key, id, workspace ou project levariam o arquivo para fora da
    pasta do project (ex.: key com "..").
    """
    problem = (portable_folder_problem(workspace_name, "workspace")
               or portable_folder_problem(project_name, "project")
               or (key_problem(key) if key else id_problem(item_id)))
    if problem:
        raise ValidationError(problem)
    ws = slugify(workspace_name)
    dm = slugify(project_name)
    rel = f"{ws}/{dm}/{key}.md" if key else f"{ws}/{dm}/{_SEM_KEY_DIR}/{item_id}.md"
    problem = path_length_problem(None, rel)
    if problem:
        raise ValidationError(problem)
    return rel


# --------------------------------------------------------------------------- helpers de campo


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _fmt_dt(value: datetime) -> str:
    """Formata um datetime (naive ou aware, assumido UTC) como "YYYY-MM-DDTHH:MM:SSZ"."""
    if value.tzinfo is not None:
        value = _utc_naive(value)
    return value.replace(microsecond=0).isoformat() + "Z"


def _utc_naive(value: datetime) -> datetime:
    """Qualquer offset (ou `Z`) vira UTC sem tzinfo, o formato interno."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_dt(raw: Any, field: str) -> datetime:
    if isinstance(raw, datetime):
        return _utc_naive(raw)
    if isinstance(raw, date):  # YAML lê `2020-01-01` sem aspas como data
        return datetime(raw.year, raw.month, raw.day)
    if not isinstance(raw, str) or not raw:
        raise ValidationError(f"Frontmatter com {field!r} inválido ou ausente: {_s(raw)}")
    text = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        return _utc_naive(datetime.fromisoformat(text))
    except ValueError as exc:
        raise ValidationError(f"Frontmatter com {field!r} em formato inválido: {_s(raw)}") from exc


# --------------------------------------------------------------------------- serialize


def serialize_item(
    item: Any,
    *,
    workspace_name: str,
    project_name: str,
    subject_name: str | None,
    relations: list[dict[str, str]],
    tags: list[str],
) -> str:
    """Serializa um item (dict ou objeto com os mesmos campos) em conteúdo de arquivo
    Markdown com frontmatter YAML, na ordem do formato v2.

    Opcionais sem valor (`key`, `subject`, `subtype`, `scope`, `ttl_days`, `keywords`,
    `source`, `verified_at`, `verified_commit`) não viram linha; `origin` ausente sai
    `agent`. Item `type == "secret"` é serializado só com metadados; recusa
    (`ValidationError`) se ele trouxer algum campo de valor — o valor do segredo nunca vai pro
    git. Telemetria (`access_count`, `last_accessed`) e `expires_at` (sempre recalculado a
    partir de `updated_at` + `ttl_days`) nunca são persistidos no arquivo.
    """
    item_type = _field(item, "type")
    if item_type == "secret":
        found = [f for f in _SECRET_VALUE_FIELDS if _field(item, f) is not None]
        if found:
            raise ValidationError(
                f"Item do tipo 'secret' com campo de valor ({', '.join(found)}) não pode ser "
                "serializado para arquivo versionável (o valor nunca vai para o git)"
            )

    def optional(name: str, value: Any) -> None:
        if value is not None and value != "":
            data[name] = value

    data: dict[str, Any] = {}
    optional("key", _field(item, "key"))
    data["id"] = _field(item, "id")
    data["workspace"] = workspace_name
    data["project"] = project_name
    optional("subject", subject_name)
    data["type"] = item_type
    optional("subtype", _field(item, "subtype"))
    optional("scope", _field(item, "scope"))
    data["title"] = _field(item, "title")
    data["status"] = _field(item, "status")
    data["tags"] = list(tags)
    data["links"] = [{"title": lk["title"], "url": lk["url"]}
                     for lk in (_field(item, "links") or [])]
    data["scope_paths"] = list(_field(item, "scope_paths") or [])
    optional("ttl_days", _field(item, "ttl_days"))
    optional("keywords", _field(item, "keywords"))
    optional("source", _field(item, "source"))
    data["origin"] = _field(item, "origin") or DEFAULT_ORIGIN
    verified_at = _field(item, "verified_at")
    if verified_at is not None:
        data["verified_at"] = _fmt_dt(verified_at)
    optional("verified_commit", _field(item, "verified_commit"))
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

# Âncora YAML (`&nome`) fora de aspas: só então vale varrer os eventos atrás de alias.
_ANCHOR_HINT = re.compile(r"&[^\s&]")


def load_yaml_text(text: str, what: str) -> Any:
    """`yaml.load` seguro de um texto de arquivo da conexão, sem alias.

    Alias (`*nome`) é recusado: com âncoras aninhadas, um arquivo de 1 KB vira uma estrutura
    que, ao ser percorrida ou impressa, ocupa GBs ("billion laughs") e derruba toda leitura da
    pasta. A varredura de eventos (`yaml.parse`) é linear no texto e só roda quando há algo com
    cara de âncora. Levanta `ValidationError` (mensagem curta) se o YAML não serve.
    """
    try:
        if _ANCHOR_HINT.search(text) and any(
                isinstance(event, yaml.AliasEvent) for event in yaml.parse(text, Loader=_LOADER)):
            raise ValidationError(f"{what} com alias YAML não é aceito (tire os '*nome' e "
                                  "escreva o valor por extenso)")
        return yaml.load(text, Loader=_LOADER)  # noqa: S506 - loader seguro
    except yaml.YAMLError as exc:
        raise ValidationError(f"{what} YAML malformado: {str(exc)[:200]}") from exc


def parse_item_file(raw: str) -> dict[str, Any]:
    """Faz o caminho inverso de `serialize_item`: devolve um dict com os campos do
    frontmatter (tipados) mais `content` (o corpo do arquivo).

    Arquivo no formato antigo é traduzido na leitura (`model.translate_legacy`): é o único
    ponto de compatibilidade, e a regravação já sai em v2.

    Levanta `ValidationError` se o frontmatter estiver ausente, malformado, faltar algum
    campo obrigatório (`id`, `type`, `title`, `summary`, `status`, `created_at`,
    `updated_at`) ou trouxer valor fora da taxonomia (tipo, subtipo, status, scope, origin).
    """
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        raise ValidationError("Arquivo sem frontmatter YAML (esperado '---' no início)")
    raw_frontmatter, content = match.groups()
    data = load_yaml_text(raw_frontmatter, "Frontmatter")
    if not isinstance(data, dict):
        raise ValidationError("Frontmatter YAML malformado: esperado um mapeamento no topo")

    missing = [f for f in _REQUIRED_FIELDS if data.get(f) is None]
    if missing:
        raise ValidationError(f"Frontmatter sem campo(s) obrigatório(s): {', '.join(missing)}")

    for name in _TEXT_REQUIRED:
        _text(data, name, required=True)
    for name in _TEXT_OPTIONAL:
        _text(data, name, required=False)
    _str_list(data, "tags")
    _str_list(data, "labels")
    data = translate_legacy(data)
    _check_taxonomy(data)

    problem = id_problem(data["id"])
    if not problem and data.get("key") is not None:
        problem = key_problem(data["key"], portable=False)
    for name in ("workspace", "project"):
        if not problem and data.get(name) is not None:
            problem = folder_problem(data[name], name)
    if problem:
        raise ValidationError(f"Frontmatter com {problem}")

    verified_at = data.get("verified_at")
    parsed: dict[str, Any] = {
        "id": data["id"],
        "key": data.get("key"),
        "workspace": data.get("workspace"),
        "project": data.get("project"),
        "subject": data.get("subject"),
        "type": data["type"],
        "subtype": data.get("subtype"),
        "scope": data.get("scope"),
        "title": data["title"],
        "status": data["status"],
        "tags": _str_list(data, "tags"),
        "links": _links(data),
        "scope_paths": _str_list(data, "scope_paths"),
        "ttl_days": _int(data, "ttl_days"),
        "keywords": data.get("keywords"),
        "source": data.get("source"),
        "origin": data["origin"],
        "verified_at": (_parse_dt(verified_at, "verified_at")
                        if verified_at is not None else None),
        "verified_commit": data.get("verified_commit"),
        "created_at": _parse_dt(data["created_at"], "created_at"),
        "updated_at": _parse_dt(data["updated_at"], "updated_at"),
        "relations": _relations(data),
        "summary": data["summary"],
        "content": content,
    }
    return parsed


# Campos de texto do frontmatter: um YAML válido com outro tipo (`title: 2024`, `id: [a]`)
# derrubaria quem lê o item; aqui ele vira erro do arquivo.
_TEXT_REQUIRED = ("id", "type", "title", "summary", "status")
_TEXT_OPTIONAL = ("key", "workspace", "project", "subject", "subtype", "scope", "keywords",
                  "source", "origin", "verified_commit")


def _check_taxonomy(data: dict[str, Any]) -> None:
    """Tipo, subtipo, status, scope e origin dentro da taxonomia (já traduzidos).

    Na leitura o status não é cruzado com o tipo: um arquivo editado à mão com `done` numa
    regra continua legível (a gravação pelo `item_save` é que recusa).
    """
    item_type = data["type"]
    if item_type not in TYPES:
        raise ValidationError(f"Frontmatter com 'type' fora da taxonomia: {_s(item_type)} "
                              f"(válidos: {', '.join(TYPES)})")
    subtype = data.get("subtype")
    if subtype is not None and subtype not in TYPES[item_type]:
        raise ValidationError(f"Frontmatter com 'subtype' inválido para {item_type}: "
                              f"{_s(subtype)} (válidos: {', '.join(TYPES[item_type]) or '—'})")
    status = data["status"]
    if status not in STATUSES + SPEC_STATUSES:
        raise ValidationError(f"Frontmatter com 'status' inválido: {_s(status)} "
                              f"(válidos: {', '.join(STATUSES + SPEC_STATUSES)})")
    for name, valid in (("scope", SCOPES), ("origin", ORIGINS)):
        value = data.get(name)
        if value is not None and value not in valid:
            raise ValidationError(f"Frontmatter com {name!r} inválido: {_s(value)} "
                                  f"(válidos: {', '.join(valid)})")


def _text(data: dict[str, Any], name: str, *, required: bool) -> None:
    value = data.get(name)
    if value is None and not required:
        return
    if not isinstance(value, str):
        raise ValidationError(f"Frontmatter com {name!r} que não é texto: {_s(value)}")


def _str_list(data: dict[str, Any], name: str) -> list[str]:
    value = data.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"Frontmatter com {name!r} que não é lista de textos: {_s(value)}")
    return list(value)


def _int(data: dict[str, Any], name: str) -> int | None:
    value = data.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Frontmatter com {name!r} que não é número inteiro: {_s(value)}")
    return value


def _links(data: dict[str, Any]) -> list[dict[str, str]]:
    value = data.get("links")
    if value is None:
        return []
    ok = isinstance(value, list) and all(
        isinstance(lk, dict) and isinstance(lk.get("title"), str)
        and isinstance(lk.get("url"), str)
        for lk in value
    )
    if not ok:
        raise ValidationError(
            f"Frontmatter com 'links' fora do formato [{{title, url}}]: {_s(value)}"
        )
    return [{"title": lk["title"], "url": lk["url"]} for lk in value]


def _relations(data: dict[str, Any]) -> list[dict[str, str]]:
    value = data.get("relations")
    if value is None:
        return []
    ok = isinstance(value, list) and all(
        isinstance(r, dict) and isinstance(r.get("type"), str)
        and isinstance(r.get("target"), str)
        for r in value
    )
    if not ok:
        raise ValidationError(
            f"Frontmatter com 'relations' fora do formato [{{type, target}}]: {_s(value)}"
        )
    return [{"type": r["type"], "target": r["target"]} for r in value]
