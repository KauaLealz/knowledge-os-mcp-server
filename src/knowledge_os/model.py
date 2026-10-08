"""Modelo do segundo cérebro (v2): a taxonomia fechada e a validação de uma entrada de item.

Fonte única dos valores aceitos — tipos e subtipos, status, scope, origin, tipos de relação e
de feedback — e das regras que dependem só deles. Puro: sem I/O e sem importar serviços, para
que serviços, MCP, API e as instruções do MCP (`taxonomy_markdown`) leiam daqui sem ciclo.

- `validate_entry` normaliza e valida uma entrada do `item_save` e devolve os avisos (modelo do
  `content` por subtipo, key fora do padrão). Valida os campos presentes: o que falta (numa
  atualização parcial) não é cobrado aqui.
- `translate_legacy` é o único ponto de compatibilidade com o formato antigo: o parser de
  arquivo chama na leitura, e a regravação já sai em v2.

Erros de validação dizem como corrigir (os valores válidos).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from knowledge_os.exceptions import ValidationError

# --------------------------------------------------------------------------- taxonomia

TYPES: dict[str, tuple[str, ...]] = {
    "rule": ("code", "pattern", "security", "business", "process", "decision"),
    "howto": ("procedure", "troubleshoot"),
    "context": ("product", "map", "stack", "glossary", "environment"),
    "spec": ("change", "setup", "dream"),
    "secret": (),
}

STATUSES = ("active", "review", "archived")
SPEC_STATUSES = ("draft", "done")  # só `spec`
EXPIRED = "expired"  # derivado do ttl vencido, nunca gravado
DEFAULT_STATUS = "active"

SCOPES = ("scoped", "workspace", "global")
DEFAULT_SCOPE = "scoped"  # nada explícito na cadeia item → subject → project → workspace

ORIGINS = ("user", "code", "agent")
DEFAULT_ORIGIN = "agent"

RELATION_TYPES = ("related_to", "depends_on", "implements", "references", "supersedes",
                  "derived_from")
OUTCOMES = ("helped", "irrelevant", "wrong", "outdated", "verified")

# Campos aceitos no `item_save` (os de local — workspace, project, subject — passam à parte).
ITEM_FIELDS = ("key", "id", "type", "subtype", "scope", "title", "summary", "content", "status",
               "tags", "links", "scope_paths", "ttl_days", "keywords", "source", "origin")
LOCATION_FIELDS = ("workspace", "project", "subject")

# Modelo do `content` por (tipo, subtipo): o que falta só vira aviso.
CONTENT_MODEL: dict[tuple[str, str], tuple[str, ...]] = {
    ("rule", "decision"): ("## Por quê", "## Alternativa descartada"),
    ("rule", "pattern"): ("Arquivo-modelo:",),
    ("howto", "troubleshoot"): ("## Sintoma", "## Causa", "## Solução"),
}
LINKS_REQUIRED = (("context", "environment"),)

_KEY_NAME = r"[a-z0-9]+(?:-[a-z0-9]+)*"
# Segmento de key que vira pasta: começa por letra ou número (nada de vazio, ".", ".." ou
# pasta oculta) e usa só letras, números, ".", "_" e "-".
_KEY_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_TAG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _listing(values: tuple[str, ...] | list[str]) -> str:
    return ", ".join(values)


# --------------------------------------------------------------------------- campos isolados


def key_problem(key: Any) -> str | None:
    """Motivo pelo qual a key não serve de path dentro do project (None se serve).

    A key vira `<ws>/<pj>/<key>.md`: cada segmento separado por "/" precisa começar por letra
    ou número e ter só letras, números, ".", "_" e "-". Isso recusa segmento vazio, ".", "..",
    pasta oculta, barra invertida, ":" e caminho absoluto.
    """
    if not isinstance(key, str) or not key or len(key) > 200:
        return "key deve ser um texto de 1 a 200 caracteres"
    if not all(_KEY_SEGMENT_RE.fullmatch(seg) for seg in key.split("/")):
        return (f"key inválida: {key!r} (cada parte entre '/' começa por letra ou número e "
                "usa só letras, números, '.', '_' e '-')")
    return None


def key_warnings(key: str | None, item_type: str | None) -> list[str]:
    """Aviso se a key não segue `<tipo>/<nome>` (nome em minúsculas com '-')."""
    if not key or not item_type:
        return []
    if re.fullmatch(rf"{re.escape(item_type)}/{_KEY_NAME}", key):
        return []
    return [f"key {key!r} fora do padrão {item_type}/<nome> (nome em minúsculas com '-', "
            f"ex.: {item_type}/money-em-pagamentos); gravado assim mesmo"]


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).casefold()


def content_warnings(item_type: str | None, subtype: str | None, content: str | None,
                     links: list[dict[str, str]] | None = None) -> list[str]:
    """Avisos do modelo do `content` por subtipo (nunca impedem a gravação)."""
    if not item_type or not subtype:
        return []
    out: list[str] = []
    expected = CONTENT_MODEL.get((item_type, subtype), ())
    folded = _fold(content or "")
    missing = [part for part in expected if _fold(part) not in folded]
    if missing:
        out.append(f"{item_type}/{subtype} sem {', '.join(repr(m) for m in missing)} no "
                   "content: acrescente para seguir o modelo")
    if (item_type, subtype) in LINKS_REQUIRED and not links:
        out.append(f"{item_type}/{subtype} sem links: informe ao menos um em "
                   "links=[{title, url}]")
    return out


def normalize_tag(name: Any) -> str:
    """Nome de tag em kebab-case minúsculo, sem acento; vazio é erro."""
    if not isinstance(name, str):
        raise ValidationError(f"tag deve ser texto: {name!r}")
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(name.strip())).strip("-")
    if not _TAG_RE.fullmatch(slug):
        raise ValidationError(f"tag inválida: {name!r} (use kebab-case, ex.: pagamentos-pix)")
    return slug


def statuses_for(item_type: str | None) -> tuple[str, ...]:
    """Status gravável para o tipo (sem tipo: todos)."""
    if item_type is None or item_type == "spec":
        return STATUSES + SPEC_STATUSES
    return STATUSES


def _check_choice(name: str, value: Any, valid: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value.strip().lower() not in valid:
        raise ValidationError(f"{name} inválido: {value!r}. Válidos: {_listing(valid)}")
    return value.strip().lower()


def _check_type(value: Any) -> str:
    return _check_choice("type", value, tuple(TYPES))


def _check_subtype(item_type: str | None, value: Any) -> str | None:
    if value is None or value == "":
        return None
    if item_type == "secret":
        raise ValidationError("secret não tem subtipo: remova subtype")
    if item_type is None:
        valid = tuple(s for subs in TYPES.values() for s in subs)
        return _check_choice("subtype", value, valid)
    valid = TYPES[item_type]
    if not isinstance(value, str) or value.strip().lower() not in valid:
        raise ValidationError(f"subtype inválido para {item_type}: {value!r}. "
                              f"Válidos: {_listing(valid)}")
    return value.strip().lower()


def _check_status(item_type: str | None, value: Any) -> str:
    valid = statuses_for(item_type)
    if isinstance(value, str) and value.strip().lower() in valid:
        return value.strip().lower()
    hint = ""
    if isinstance(value, str) and value.strip().lower() in SPEC_STATUSES:
        hint = f" ({value} só em spec)"
    elif value == EXPIRED:
        hint = " (expired é derivado do ttl_days, nunca gravado)"
    raise ValidationError(f"status inválido: {value!r}{hint}. Válidos: {_listing(valid)}")


def _check_text(name: str, value: Any, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValidationError(f"{name} não pode ser vazio")
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{name} deve ser texto: {value!r}")
    if required and not value.strip():
        raise ValidationError(f"{name} não pode ser vazio")
    return value


def _check_str_list(name: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"{name} deve ser lista de textos: {value!r}")
    return [v.strip() for v in value if v.strip()]


def check_links(value: Any) -> list[dict[str, str]]:
    """`links` = `[{title, url}]`; sem `title`, vale a própria url."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"links deve ser lista de {{title, url}}: {value!r}")
    out: list[dict[str, str]] = []
    for link in value:
        url = link.get("url") if isinstance(link, dict) else None
        title = link.get("title") if isinstance(link, dict) else None
        if not isinstance(url, str) or not url.strip() or (
                title is not None and not isinstance(title, str)):
            raise ValidationError(
                f"link inválido: {link!r}. Formato: {{\"title\": \"Painel\", \"url\": \"https://...\"}}"
            )
        out.append({"title": (title or "").strip() or url.strip(), "url": url.strip()})
    return out


def _check_ttl(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"ttl_days deve ser inteiro positivo (dias): {value!r}")
    return value


# --------------------------------------------------------------------------- entrada


def validate_entry(entry: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Normaliza e valida uma entrada do `item_save`; devolve (campos limpos, avisos).

    Campo fora de `ITEM_FIELDS` (e dos de local: workspace, project, subject) é erro que lista
    os válidos. Valida só o que veio; as regras que cruzam campos (subtipo e status por tipo)
    usam o `type` da entrada — numa atualização parcial, quem chama manda o tipo do item.
    Defaults (status, origin) não são preenchidos aqui: numa atualização apagariam o valor atual.
    """
    if not isinstance(entry, dict):
        raise ValidationError(f"Cada item deve ser um objeto: {entry!r}")
    unknown = [k for k in entry if k not in ITEM_FIELDS and k not in LOCATION_FIELDS]
    if unknown:
        raise ValidationError(
            f"Campo(s) desconhecido(s): {', '.join(sorted(unknown))}. "
            f"Válidos: {_listing(ITEM_FIELDS + LOCATION_FIELDS)}"
        )
    clean: dict[str, Any] = {}
    item_type = None
    if "type" in entry:
        item_type = clean["type"] = _check_type(entry["type"])
    for name in LOCATION_FIELDS:
        if name in entry:
            clean[name] = entry[name]
    if "subtype" in entry:
        clean["subtype"] = _check_subtype(item_type, entry["subtype"])
    if entry.get("status") is not None:
        clean["status"] = _check_status(item_type, entry["status"])
    if entry.get("scope") is not None:
        clean["scope"] = _check_choice("scope", entry["scope"], SCOPES)
    elif "scope" in entry:
        clean["scope"] = None
    if entry.get("origin") is not None:
        clean["origin"] = _check_choice("origin", entry["origin"], ORIGINS)
    for name in ("title", "summary"):
        if name in entry:
            clean[name] = _check_text(name, entry[name], required=True).strip()
    for name in ("content", "keywords", "source", "id"):
        if name in entry:
            clean[name] = _check_text(name, entry[name], required=False)
    if entry.get("key") is not None:
        problem = key_problem(entry["key"])
        if problem:
            raise ValidationError(problem)
        clean["key"] = entry["key"]
    if "tags" in entry:
        clean["tags"] = list(dict.fromkeys(
            normalize_tag(t) for t in _check_str_list("tags", entry["tags"])
        ))
    if "links" in entry:
        clean["links"] = check_links(entry["links"])
    if "scope_paths" in entry:
        clean["scope_paths"] = _check_str_list("scope_paths", entry["scope_paths"])
    if "ttl_days" in entry:
        clean["ttl_days"] = _check_ttl(entry["ttl_days"])

    warnings = key_warnings(clean.get("key"), item_type)
    warnings += content_warnings(item_type, clean.get("subtype"), clean.get("content"),
                                 clean.get("links"))
    return clean, warnings


# --------------------------------------------------------------------------- leitura antiga

_LEGACY_TYPES: dict[str, tuple[str, str | None]] = {
    "insight": ("rule", "decision"),
    "procedure": ("howto", None),
    "knowledge": ("howto", "troubleshoot"),
    "pattern": ("rule", "pattern"),
    "task": ("spec", None),
}
_LEGACY_STATUSES = {"superseded": "archived", "deprecated": "archived"}
_LEGACY_FIELDS = ("memory_class", "labels", "importance", "confidence")
_SENSITIVE_WORD = "sensivel"


def translate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Traduz, na leitura, o frontmatter de um arquivo no formato antigo para o v2.

    Arquivo v2 (com `origin` e sem campo antigo) passa intacto, salvo um tipo ou status antigo
    que tenha sobrado. Os mapeamentos: insight → rule/decision; procedure → howto; knowledge →
    howto/troubleshoot com status review; pattern → rule/pattern; task → spec; rule com a
    palavra "sensivel" nas keywords → rule/security (a palavra sai); superseded/deprecated →
    archived; labels somam-se às tags; memory_class/importance/confidence saem (ephemeral
    mantém o ttl_days); sem origin → "user" no arquivo antigo, "agent" nos demais.
    """
    out = dict(data)
    legacy = any(name in out for name in _LEGACY_FIELDS)
    old_type = out.get("type")
    status = out.get("status")
    if isinstance(status, str) and status in _LEGACY_STATUSES:
        out["status"] = _LEGACY_STATUSES[status]
    if isinstance(old_type, str) and old_type in _LEGACY_TYPES:
        new_type, subtype = _LEGACY_TYPES[old_type]
        out["type"] = new_type
        if subtype and not out.get("subtype"):
            out["subtype"] = subtype
        if old_type == "knowledge" and out.get("status") == "active":
            out["status"] = "review"
    if legacy and old_type == "rule" and isinstance(out.get("keywords"), str):
        words = out["keywords"].split()
        if _SENSITIVE_WORD in words:
            out["keywords"] = " ".join(w for w in words if w != _SENSITIVE_WORD) or None
            if not out.get("subtype"):
                out["subtype"] = "security"
    if "labels" in out:
        labels = out.pop("labels") or []
        tags = out.get("tags") or []
        if isinstance(labels, list) and isinstance(tags, list):
            out["tags"] = list(dict.fromkeys([*tags, *labels]))
    memory_class = out.pop("memory_class", None)
    out.pop("importance", None)
    out.pop("confidence", None)
    if legacy and memory_class != "ephemeral":
        out.pop("ttl_days", None)
    if out.get("origin") is None:
        out["origin"] = "user" if memory_class is not None else DEFAULT_ORIGIN
    return out


# --------------------------------------------------------------------------- instruções


def taxonomy_markdown() -> str:
    """Tabelas da taxonomia para as instruções do MCP (geradas daqui, nunca à mão)."""
    lines = ["| Tipo | Subtipos (opcionais) |", "|---|---|"]
    for item_type, subtypes in TYPES.items():
        lines.append(f"| `{item_type}` | {', '.join(f'`{s}`' for s in subtypes) or '—'} |")
    models = [f"`{t}/{s}` → {', '.join(f'`{p}`' for p in parts)}"
              for (t, s), parts in CONTENT_MODEL.items()]
    models += [f"`{t}/{s}` → ao menos um item em `links`" for t, s in LINKS_REQUIRED]
    lines += [
        "",
        "| Campo | Valores |",
        "|---|---|",
        f"| status | {', '.join(f'`{s}`' for s in STATUSES)}; só `spec`: "
        f"{', '.join(f'`{s}`' for s in SPEC_STATUSES)} (`{EXPIRED}` é derivado do ttl) |",
        f"| scope | {', '.join(f'`{s}`' for s in SCOPES)} (sem valor: herda subject → project "
        f"→ workspace; nada explícito = `{DEFAULT_SCOPE}`) |",
        f"| origin | {', '.join(f'`{s}`' for s in ORIGINS)} (padrão `{DEFAULT_ORIGIN}`) |",
        f"| relação | {', '.join(f'`{s}`' for s in RELATION_TYPES)} |",
        f"| feedback (outcome) | {', '.join(f'`{s}`' for s in OUTCOMES)} |",
        "",
        "Key: `<tipo>/<nome>` (nome em minúsculas com `-`); fora do padrão grava com aviso, e a "
        "key de um item existente nunca muda.",
        "",
        "Modelo do `content` (só avisa): " + "; ".join(models) + ".",
    ]
    return "\n".join(lines) + "\n"
