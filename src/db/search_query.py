"""Normalização de consultas de busca para o FTS5, pensada para PT-BR sem embeddings.

A recuperação depende só de palavras, então a consulta do agente é reduzida ao radical
aproximado de cada termo e casada por prefixo: "migração", "migrações" e "migrar" viram
`migra*`. Consultas que já usam a sintaxe do FTS5 passam intactas.
"""

import re
import unicodedata

_FTS_SYNTAX = re.compile(r'["*:()^]|\b(AND|OR|NOT|NEAR)\b')
_WORD = re.compile(r"[a-z0-9_]+")
_MIN_STEM = 4
_STOPWORDS = frozenset(
    "a o e de da do das dos em no na nos nas um uma uns umas para por com sem que como "
    "ao aos se ou mais the of and to in for on with is are be by an at as".split()
)
# Sufixos já sem acento, do mais longo ao mais curto; corta só se sobrar radical útil.
_SUFFIXES = (
    "amentos", "imentos", "amento", "imento", "mente", "idades", "idade", "acoes", "icoes",
    "coes", "soes", "acao", "icao", "cao", "sao", "oes", "aes", "ais", "eis", "ois", "ar",
    "er", "ir", "es", "as", "os", "s",
)


def strip_accents(text: str) -> str:
    """Remove diacríticos (á→a, ç→c) mantendo o resto do texto."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def stem(term: str) -> str:
    """Radical aproximado em PT-BR (com bom efeito em inglês para plurais)."""
    for suffix in _SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= _MIN_STEM:
            return term[: -len(suffix)]
    return term


def terms(query: str) -> list[str]:
    """Termos úteis da consulta: minúsculos, sem acento, sem stopwords, com radical."""
    words = _WORD.findall(strip_accents(query.lower()))
    seen: dict[str, None] = {}
    for word in words:
        if len(word) >= 2 and word not in _STOPWORDS:
            seen.setdefault(stem(word), None)
    return list(seen)


def is_raw_fts(query: str) -> bool:
    """True se a consulta já usa operadores do FTS5 e deve ser usada como está."""
    return bool(_FTS_SYNTAX.search(query))


def match_expressions(query: str) -> list[str]:
    """Expressões MATCH a tentar, em ordem: todos os termos (AND) e, se >1, qualquer (OR)."""
    query = query.strip()
    if not query:
        return []
    if is_raw_fts(query):
        return [query]
    found = terms(query)
    if not found:
        return []
    quoted = [f'"{t}"*' for t in found]
    expressions = [" ".join(quoted)]
    if len(quoted) > 1:
        expressions.append(" OR ".join(quoted))
    return expressions
