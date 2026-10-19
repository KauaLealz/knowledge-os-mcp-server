"""Modelo do segundo cérebro (v6): a taxonomia enxuta e a validação mínima de um item.

Fonte única dos valores aceitos — os 5 tipos, as tags de base (ciclo e nuance) e os tipos de
link entre itens — e das regras de key/tag. Puro: sem I/O e sem importar serviços, para que
serviços, MCP, API e as instruções do MCP (`taxonomy_markdown`) leiam daqui sem ciclo.

Schema mínimo por decisão de design (v6):
- Não há `subtype`, `scope`, `status`, `origin`, `ttl_days`, `keywords`, `source` nem feedback.
  A nuance e o ciclo vivem em TAGS (não em campos); o alcance vem de onde o item mora na
  hierarquia (workspace → project → subject), não de um campo.
- O guia de COMO escrever cada tipo vive no harness, não aqui. `validate_entry` valida só o
  essencial (type, key, title/summary, tags, links).
- `links` é unificado: liga um item a outro item (`depends_on`/`relates_to`) ou a uma
  referência externa (URL ou caminho/glob de arquivo).

Erros de validação dizem como corrigir (os valores válidos).
"""

from __future__ import annotations

import re
import reprlib
import unicodedata
from typing import Any
from urllib.parse import urlsplit

from knowledge_os.exceptions import ValidationError

# --------------------------------------------------------------------------- taxonomia

TYPES: tuple[str, ...] = ("rule", "howto", "context", "work", "secret")

# Tags de base (em inglês), semeadas no setup; o agente pode criar novas. O cérebro não força
# nenhuma — são vocabulário sugerido. Ciclo marca o andamento (sobretudo de `work`); nuance é o
# que antes era subtipo.
LIFECYCLE_TAGS: tuple[str, ...] = ("draft", "active", "done", "archived")
NUANCE_TAGS: tuple[str, ...] = ("decision", "troubleshoot", "security", "pattern", "map",
                                "glossary", "product", "environment", "business", "process")
BASE_TAGS: tuple[str, ...] = LIFECYCLE_TAGS + NUANCE_TAGS

# Link de um item para outro item.
LINK_RELATIONS: tuple[str, ...] = ("depends_on", "relates_to")

# Campos aceitos no `item_save` (os de local — workspace, project, subject — passam à parte).
ITEM_FIELDS = ("key", "id", "type", "title", "summary", "content", "tags", "links")
LOCATION_FIELDS = ("workspace", "project", "subject")

_KEY_NAME = r"[a-z0-9]+(?:-[a-z0-9]+)*"
# Segmento de key que vira pasta: começa por letra ou número (nada de vazio, ".", ".." ou
# pasta oculta) e usa só letras, números, ".", "_" e "-".
_KEY_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_TAG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _listing(values: tuple[str, ...] | list[str]) -> str:
    return ", ".join(values)


# --------------------------------------------------------------------------- campos isolados


# Nomes que o Windows reserva para dispositivos (com ou sem extensão: `nul.txt` também).
WINDOWS_RESERVED = frozenset(
    ["con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
     *(f"lpt{i}" for i in range(1, 10))]
)


def segment_problem(segment: str, what: str) -> str | None:
    """Motivo pelo qual o segmento de path não é portável para o Windows (None se é).

    O NTFS tira ponto e espaço do fim do nome (`rule.` e `rule` viram o mesmo arquivo) e não
    aceita os nomes de dispositivo (`con`, `nul`, `com1`... também com extensão). Um segmento
    assim faria dois itens dividirem um arquivo — ou o arquivo nunca seria gravado.
    """
    if segment != segment.rstrip(". "):
        return (f"{what} inválido: {_short(segment)} termina em '.' ou espaço, que o Windows "
                "descarta (dois nomes virariam o mesmo arquivo); tire o ponto/espaço do fim")
    if segment.split(".", 1)[0].casefold() in WINDOWS_RESERVED:
        return (f"{what} inválido: {_short(segment)} é um nome reservado do Windows "
                f"({', '.join(sorted(WINDOWS_RESERVED))}); use outro nome (ex.: "
                f"{segment.split('.', 1)[0].lower()}-regras)")
    return None


_REPR = reprlib.Repr(maxlevel=2, maxlist=4, maxdict=4, maxstring=60, maxother=60,
                     maxlong=40)


def short_repr(value: Any, limit: int = 80) -> str:
    """`repr` cortado (`reprlib` + no máximo `limit` caracteres): a mensagem de erro nunca
    cresce com o valor recebido — nem com uma estrutura aninhada enorme."""
    text = _REPR.repr(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


_short = short_repr


def key_problem(key: Any, *, portable: bool = True) -> str | None:
    """Motivo pelo qual a key não serve de path dentro do project (None se serve).

    A key vira `<ws>/<pj>/<key>.md`: cada segmento separado por "/" precisa começar por letra
    ou número e ter só letras, números, ".", "_" e "-". Isso recusa segmento vazio, ".", "..",
    pasta oculta, barra invertida, ":" e caminho absoluto. Com `portable` (toda gravação),
    recusa também o que o Windows não guarda (`segment_problem`); a leitura de um arquivo que
    já existe passa `portable=False`, para não sumir com ele.
    """
    if not isinstance(key, str) or not key or len(key) > 200:
        return "key deve ser um texto de 1 a 200 caracteres"
    if not all(_KEY_SEGMENT_RE.fullmatch(seg) for seg in key.split("/")):
        return (f"key inválida: {_short(key)} (cada parte entre '/' começa por letra ou número "
                "e usa só letras, números, '.', '_' e '-')")
    if portable:
        for seg in key.split("/"):
            problem = segment_problem(seg, "key")
            if problem:
                return problem
    return None


def key_warnings(key: str | None, item_type: str | None) -> list[str]:
    """Aviso se a key não segue `<tipo>/<nome>` (nome em minúsculas com '-')."""
    if not key or not item_type:
        return []
    if re.fullmatch(rf"{re.escape(item_type)}/{_KEY_NAME}", key):
        return []
    return [f"key {_short(key)} fora do padrão {item_type}/<nome> (nome em minúsculas com '-', "
            f"ex.: {item_type}/money-em-pagamentos); gravado assim mesmo"]


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).casefold()


def normalize_tag(name: Any) -> str:
    """Nome de tag em kebab-case minúsculo, sem acento; vazio é erro."""
    if not isinstance(name, str):
        raise ValidationError(f"tag deve ser texto: {_short(name)}")
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(name.strip())).strip("-")
    if not _TAG_RE.fullmatch(slug):
        raise ValidationError(f"tag inválida: {_short(name)} (use kebab-case, ex.: pagamentos-pix)")
    return slug


def _check_choice(name: str, value: Any, valid: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value.strip().lower() not in valid:
        raise ValidationError(f"{name} inválido: {_short(value)}. Válidos: {_listing(valid)}")
    return value.strip().lower()


def _check_type(value: Any) -> str:
    return _check_choice("type", value, TYPES)


def _check_text(name: str, value: Any, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValidationError(f"{name} não pode ser vazio")
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{name} deve ser texto: {_short(value)}")
    if required and not value.strip():
        raise ValidationError(f"{name} não pode ser vazio")
    return value


def _check_str_list(name: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"{name} deve ser lista de textos: {_short(value)}")
    return [v.strip() for v in value if v.strip()]


# --------------------------------------------------------------------------- links

LINK_SCHEMES = ("http", "https", "mailto")

# Limites de um link de caminho/glob: cada padrão vira um casamento de glob a cada busca.
MAX_LINKS = 50
MAX_PATH_CHARS = 200
MAX_PATH_WILDCARDS = 8


def check_links(value: Any) -> list[dict[str, str]]:
    """`links` unificado — cada entrada liga o item a UMA coisa:

    - a outro item:        {"item": "<key>", "rel": "depends_on" | "relates_to"}
    - a uma URL externa:   {"url": "http(s)/mailto://...", "title"?: "..."}
    - a um arquivo/glob:   {"path": "src/payments/**"}  (o que o `scope_paths` fazia)

    `javascript:`/`data:`/`file:` em `url` viram código ou apontam para fora: só `LINK_SCHEMES`.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(
            "links deve ser lista de {item, rel} | {url[, title]} | {path}: " + _short(value))
    if len(value) > MAX_LINKS:
        raise ValidationError(f"links: no máximo {MAX_LINKS} por item (recebi {len(value)})")
    out: list[dict[str, str]] = []
    for link in value:
        if not isinstance(link, dict):
            raise ValidationError(f"link inválido: {_short(link)}")
        if "item" in link:
            out.append(_check_item_link(link))
        elif "url" in link:
            out.append(_check_url_link(link))
        elif "path" in link:
            out.append(_check_path_link(link))
        else:
            raise ValidationError(
                f"link inválido: {_short(link)}. Use {{item, rel}}, {{url[, title]}} ou {{path}}")
    return out


def _check_item_link(link: dict[str, Any]) -> dict[str, str]:
    key = link.get("item")
    problem = key_problem(key, portable=False)
    if problem:
        raise ValidationError(f"link de item inválido: {problem}")
    rel = _check_choice("rel", link.get("rel"), LINK_RELATIONS)
    return {"item": key, "rel": rel}


def _check_url_link(link: dict[str, Any]) -> dict[str, str]:
    url = link.get("url")
    title = link.get("title")
    if not isinstance(url, str) or not url.strip() or (
            title is not None and not isinstance(title, str)):
        raise ValidationError(
            "link de url inválido: " + _short(link) + '. Formato: {"url": "https://...", '
            '"title": "Painel"}')
    try:
        scheme = urlsplit(url.strip()).scheme.lower()
    except ValueError:
        scheme = ""
    if scheme not in LINK_SCHEMES:
        raise ValidationError(
            f"link com esquema não aceito: {_short(url.strip())}. Aceitos: "
            f"{', '.join(LINK_SCHEMES)} (ex.: https://painel.exemplo.com)")
    out = {"url": url.strip()}
    if title and title.strip():
        out["title"] = title.strip()
    return out


def _check_path_link(link: dict[str, Any]) -> dict[str, str]:
    path = link.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValidationError(f"link de caminho inválido: {_short(link)}. Formato: {{\"path\": "
                              '"src/**/*.py"}')
    path = path.strip()
    if len(path) > MAX_PATH_CHARS:
        raise ValidationError(f"links: cada path tem até {MAX_PATH_CHARS} caracteres "
                              f"({_short(path)} tem {len(path)})")
    wildcards = path.count("*") + path.count("?")
    if wildcards > MAX_PATH_WILDCARDS:
        raise ValidationError(
            f"links: no máximo {MAX_PATH_WILDCARDS} curingas (* ou ?) por path "
            f"({_short(path)} tem {wildcards}); use ** para cruzar pastas")
    return {"path": path}


# --------------------------------------------------------------------------- entrada


def validate_entry(entry: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Normaliza e valida uma entrada do `item_save`; devolve (campos limpos, avisos).

    Valida só o essencial (v6): type na taxonomia, key no formato de path, title/summary não
    vazios (quando presentes), tags em kebab-case, links no formato unificado. Campo fora de
    `ITEM_FIELDS`/`LOCATION_FIELDS` é erro que lista os válidos. Numa atualização parcial,
    valida só o que veio.
    """
    if not isinstance(entry, dict):
        raise ValidationError(f"Cada item deve ser um objeto: {_short(entry)}")
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
    for name in ("title", "summary"):
        if name in entry:
            clean[name] = _check_text(name, entry[name], required=True).strip()
    for name in ("content", "id"):
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

    warnings = key_warnings(clean.get("key"), item_type)
    return clean, warnings


# --------------------------------------------------------------------------- instruções


def taxonomy_markdown() -> str:
    """Tabelas da taxonomia para as instruções do MCP (geradas daqui, nunca à mão)."""
    lines = [
        "| Tipo | Guarda |",
        "|---|---|",
        "| `rule` | o que deve ser seguido + o porquê (convenção, decisão, regra de negócio) |",
        "| `howto` | passos repetíveis ou diagnóstico (sintoma/causa/solução) |",
        "| `context` | pano de fundo: produto, mapa, stack, glossário, ambiente |",
        "| `work` | o trabalho: plano/spec + decisões (o porquê durável); ciclo por tag |",
        "| `secret` | referência a um segredo (sem o valor) |",
        "",
        "| Campo | Valores |",
        "|---|---|",
        f"| tags de ciclo | {', '.join(f'`{t}`' for t in LIFECYCLE_TAGS)} |",
        f"| tags de nuance (base, extensível) | {', '.join(f'`{t}`' for t in NUANCE_TAGS)} |",
        f"| link item→item (`rel`) | {', '.join(f'`{r}`' for r in LINK_RELATIONS)} |",
        "",
        "Key: `<tipo>/<nome>` (nome em minúsculas com `-`); fora do padrão grava com aviso, e a "
        "key de um item existente nunca muda.",
        "",
        "Alcance: o item vale onde mora na hierarquia (workspace → project → subject) e abaixo. "
        "Não há `scope`, `status`, `subtype`, `origin` nem expiração — a nuance e o ciclo vão em "
        "`tags`.",
        "",
        "`links` (unificado): `{item, rel}` liga a outro item; `{url[, title]}` a uma URL; "
        "`{path}` a um arquivo/glob do repositório.",
    ]
    return "\n".join(lines) + "\n"
