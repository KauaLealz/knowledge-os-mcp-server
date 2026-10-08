"""Busca textual em memória sobre os itens, pensada para PT-BR sem embeddings.

A recuperação depende só de palavras: a consulta do agente é reduzida ao radical aproximado de
cada termo e casada por PREFIXO contra os tokens do item (minúsculos, sem acento), então
"migração", "migrações" e "migrar" acham uns aos outros. Não há sintaxe de consulta: aspas,
asteriscos e "OR" são texto como qualquer outro.

Identificadores: além do token inteiro, o tokenizador gera as partes de camelCase, snake_case
e números (`ItemService.saveBatch` → `itemservice item service savebatch save batch`;
`ERR_CONN_42` → `err_conn_42 err conn 42`). A consulta recebe o mesmo tratamento, então
"save batch" e "saveBatch" acham o mesmo item, e um código de erro é achado como está.

Relevância: BM25 com pesos por campo (`FIELD_WEIGHTS`, na ordem de `FIELDS`) — a frequência de
cada termo é a soma ponderada por campo e o comprimento do documento é o total de tokens de
todos os campos. Primeiro exige todos os termos (AND); se nada casar e houver mais de um
termo, aceita qualquer um (OR). O score final multiplica o BM25 pelos fatores que quem chama
já calculou (`Candidate.distance`, `Candidate.boost`) e pelos daqui: `paths` casando
`scope_paths` (×1.5) e status `review` (×0.6). Alcance, filtros e sinais são do `ItemService`;
este módulo só ranqueia e explica (`Hit.matched_in`, `snippet`, `excerpt`).

`SearchIndex` é o índice invertido, mantido incrementalmente (`add`/`remove` por item) pelo
`FileStore`, para não tokenizar tudo a cada busca.
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from knowledge_os.storage.files import ItemRecord

FIELDS = ("title", "keywords", "summary", "tags", "subtype", "content")
FIELD_WEIGHTS = (6.0, 4.0, 3.0, 3.0, 2.0, 1.0)
PATH_FACTOR = 1.5
REVIEW_FACTOR = 0.6
SNIPPET_MAX = 160
EXCERPT_MAX = 600
_K1 = 1.2
_B = 0.75
# IDF mínimo: termo presente em quase todos os itens ainda conta um pouco (nunca negativo).
_MIN_IDF = 1e-6

# Palavra crua (com caixa, já sem acento) e as partes de um identificador dentro dela.
_RAW = re.compile(r"[A-Za-z0-9_]+")
_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_MIN_STEM = 4
_STOPWORDS = frozenset(
    "a o e de da do das dos em no na nos nas um uma uns umas para por com sem que como "
    "ao aos se ou mais the of and to in for on with is are be by an at as".split()
)
# Sufixos já sem acento, do mais longo ao mais curto; corta só se sobrar radical útil.
_SUFFIXES = (
    "amentos", "imentos", "amento", "imento", "mente", "idades", "idade", "encias", "ancias",
    "encia", "ancia", "entes", "antes", "ente", "ante", "acoes", "icoes",
    "coes", "soes", "acao", "icao", "cao", "sao", "oes", "aes", "ais", "eis", "ois", "ar",
    "er", "ir", "es", "as", "os", "s",
)


# --------------------------------------------------------------------------- normalização


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


def _words(text: str) -> list[list[str]]:
    """Cada palavra do texto como [inteiro, partes...], minúsculos e sem acento."""
    out = []
    for raw in _RAW.findall(strip_accents(text)):
        whole = raw.lower()
        group = [whole]
        for part in _PART.findall(raw):
            part = part.lower()
            if part not in group:
                group.append(part)
        out.append(group)
    return out


def tokenize(text: str | None) -> list[str]:
    """Tokens de um texto do item: minúsculos, sem acento, com as partes dos identificadores
    (sem radical: o prefixo da consulta cobre)."""
    if not text:
        return []
    return [token for group in _words(text) for token in group]


def terms(query: str) -> list[str]:
    """Termos úteis da consulta: minúsculos, sem acento, sem stopwords, com radical."""
    seen: dict[str, None] = {}
    for word in tokenize(query):
        if len(word) >= 2 and word not in _STOPWORDS:
            seen.setdefault(stem(word), None)
    return list(seen)


def query_terms(query: str) -> list[str]:
    """Prefixos a casar para a consulta.

    Só stopwords ou termos curtos ("A", "de", "UI"): usa as palavras como vieram, em vez de
    devolver nada.
    """
    query = query.strip()
    if not query:
        return []
    return terms(query) or list(dict.fromkeys(tokenize(query)))


def _field_text(record: Any, field: str) -> str | None:
    value = getattr(record, field, None)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return value


# --------------------------------------------------------------------------- paths


def _norm_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _glob_regex(glob: str) -> re.Pattern[str]:
    """Glob de caminho: `**` cruza pastas (e `/**` no fim casa a própria pasta), `*` e `?`
    ficam dentro de um segmento."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("/**", i) and i + 3 == len(glob):
            out.append("(?:/.*)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def paths_match(record: ItemRecord, paths: Sequence[str]) -> bool:
    """Algum dos `paths` casa algum glob de `record.scope_paths` (ou, se o path dado for ele
    mesmo um glob, casa um `scope_paths` literal)."""
    scopes = [_norm_path(s) for s in (record.scope_paths or []) if s and s.strip()]
    given = [_norm_path(p) for p in paths if p and p.strip()]
    for scope in scopes:
        scope_re = _glob_regex(scope)
        for path in given:
            if scope_re.match(path) or _glob_regex(path).match(scope):
                return True
    return False


# --------------------------------------------------------------------------- índice


class SearchIndex:
    """Índice invertido token -> ids, com a frequência por campo de cada item.

    `add` substitui o que havia para o mesmo id; `remove` tira o item. As estatísticas do
    BM25 (total de itens, comprimento médio) são as do índice inteiro, não só dos itens
    filtrados numa busca.
    """

    def __init__(self) -> None:
        # id -> {token: (tf por campo)}
        self._docs: dict[str, dict[str, tuple[int, ...]]] = {}
        self._lengths: dict[str, int] = {}
        self._postings: dict[str, set[str]] = {}
        self._total_length = 0
        self._vocab: list[str] = []
        self._vocab_dirty = False

    def __len__(self) -> int:
        return len(self._docs)

    def __contains__(self, item_id: object) -> bool:
        return item_id in self._docs

    def add(self, record: ItemRecord) -> None:
        """Indexa (ou reindexa) um item."""
        self.remove(record.id)
        freqs: dict[str, list[int]] = {}
        length = 0
        for pos, field in enumerate(FIELDS):
            for token in tokenize(_field_text(record, field)):
                freqs.setdefault(token, [0] * len(FIELDS))[pos] += 1
                length += 1
        self._docs[record.id] = {t: tuple(f) for t, f in freqs.items()}
        self._lengths[record.id] = length
        self._total_length += length
        for token in freqs:
            ids = self._postings.get(token)
            if ids is None:
                self._postings[token] = {record.id}
                self._vocab_dirty = True
            else:
                ids.add(record.id)

    def remove(self, item_id: str) -> None:
        """Tira um item do índice (sem efeito se ele não estiver lá)."""
        doc = self._docs.pop(item_id, None)
        if doc is None:
            return
        self._total_length -= self._lengths.pop(item_id)
        for token in doc:
            ids = self._postings[token]
            ids.discard(item_id)
            if not ids:
                del self._postings[token]
                self._vocab_dirty = True

    def tokens_with_prefix(self, prefix: str) -> list[str]:
        """Tokens do vocabulário que começam com `prefix`."""
        if self._vocab_dirty:
            self._vocab = sorted(self._postings)
            self._vocab_dirty = False
        start = bisect.bisect_left(self._vocab, prefix)
        found = []
        for token in self._vocab[start:]:
            if not token.startswith(prefix):
                break
            found.append(token)
        return found

    def docs_for(self, prefix: str) -> set[str]:
        """Ids dos itens com algum token que começa com `prefix`."""
        ids: set[str] = set()
        for token in self.tokens_with_prefix(prefix):
            ids |= self._postings[token]
        return ids

    def field_hits(self, item_id: str, prefix: str) -> list[int]:
        """Frequência de `prefix` em cada campo do item (na ordem de `FIELDS`)."""
        doc = self._docs.get(item_id, {})
        totals = [0] * len(FIELDS)
        for token in self.tokens_with_prefix(prefix):
            tf = doc.get(token)
            if tf:
                totals = [a + b for a, b in zip(totals, tf, strict=True)]
        return totals

    def score(self, item_id: str, prefixes: list[str], matched: dict[str, set[str]]) -> float:
        """BM25 do item para os prefixos (só os que casaram contam)."""
        n_docs = len(self._docs)
        avg_length = (self._total_length / n_docs) if n_docs else 0.0
        length = self._lengths[item_id]
        norm = _K1 * (1 - _B + _B * (length / avg_length if avg_length else 0.0))
        total = 0.0
        for prefix in prefixes:
            if item_id not in matched[prefix]:
                continue
            tf = self.field_hits(item_id, prefix)
            freq = sum(w * f for w, f in zip(FIELD_WEIGHTS, tf, strict=True))
            if not freq:
                continue
            n = len(matched[prefix])
            idf = math.log((n_docs - n + 0.5) / (n + 0.5))
            total += max(idf, _MIN_IDF) * (freq * (_K1 + 1)) / (freq + norm)
        return total


# --------------------------------------------------------------------------- busca


@dataclass(frozen=True)
class Candidate:
    """Item que pode aparecer na busca, com os fatores que quem chama já decidiu."""

    record: ItemRecord
    distance: float = 1.0  # alcance: 1.0 / 0.85 / 0.7 (services/scope.py)
    boost: float = 1.0  # sinais (helped/opened/irrelevant), calculado por quem chama


@dataclass
class Hit:
    """Resultado ranqueado e explicado."""

    record: ItemRecord
    score: float
    matched_in: list[str]  # campos de FIELDS que casaram, mais "path"
    snippet: str  # até SNIPPET_MAX caracteres do primeiro campo que casou
    excerpt: str | None = None  # só com `paths` casando: começo do content


def _snippet(text: str, prefixes: list[str]) -> str:
    """Trecho de `text` com o primeiro prefixo que aparecer no meio."""
    # Texto normalizado caractere a caractere, guardando a posição original de cada um.
    norm: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(text):
        for c in strip_accents(ch).lower():
            norm.append(c)
            where.append(i)
    flat = "".join(norm)
    pos, size = 0, 0
    for prefix in prefixes:
        found = re.search(r"(?<![a-z0-9])" + re.escape(prefix), flat)
        index = found.start() if found else flat.find(prefix)
        if index >= 0:
            pos, size = where[index], len(prefix)
            break
    start = max(0, pos - (SNIPPET_MAX - size) // 2)
    end = min(len(text), start + SNIPPET_MAX)
    start = max(0, end - SNIPPET_MAX)
    return " ".join(text[start:end].split())[:SNIPPET_MAX]


def _excerpt(content: str | None) -> str:
    """Começo do content até EXCERPT_MAX caracteres, cortado em limite de palavra."""
    text = (content or "").strip()
    if len(text) <= EXCERPT_MAX:
        return text
    cut = text[:EXCERPT_MAX]
    if not text[EXCERPT_MAX].isspace():
        space = max(cut.rfind(" "), cut.rfind("\n"), cut.rfind("\t"))
        if space > 0:
            cut = cut[:space]
    return cut.rstrip()


def _factor(cand: Candidate, on_path: bool) -> float:
    factor = cand.distance * cand.boost
    if on_path:
        factor *= PATH_FACTOR
    if cand.record.status == "review":
        factor *= REVIEW_FACTOR
    return factor


def search(
    candidates: Iterable[Candidate],
    query: str,
    limit: int,
    *,
    index: SearchIndex | None = None,
    paths: Sequence[str] | None = None,
) -> list[Hit]:
    """Ranqueia `candidates` para `query` e devolve até `limit` resultados explicados.

    Score: BM25 × distance × boost × (1.5 se `paths` casa `scope_paths`) × (0.6 se `review`);
    sem consulta, o mesmo sem o BM25 (e todos entram). Empate: `updated_at` mais novo antes;
    depois a ordem de `candidates`. `index` é o índice já mantido (o do `FileStore`); sem ele,
    um índice temporário é montado só com os candidatos. Itens fora do índice não são
    encontrados por texto.
    """
    unique: dict[str, Candidate] = {}
    for cand in candidates:
        unique.setdefault(cand.record.id, cand)
    cands = list(unique.values())
    limit = max(limit, 0)
    on_path = {c.record.id: bool(paths) and paths_match(c.record, paths or ()) for c in cands}

    def hit(cand: Candidate, score: float, matched: list[str], snippet: str) -> Hit:
        hit_path = on_path[cand.record.id]
        return Hit(
            record=cand.record, score=score,
            matched_in=matched + (["path"] if hit_path else []), snippet=snippet,
            excerpt=_excerpt(cand.record.content) if hit_path else None,
        )

    prefixes = query_terms(query)
    if not prefixes:
        if query.strip():
            return []
        hits = [hit(c, _factor(c, on_path[c.record.id]), [], "") for c in cands]
        return _ordered(hits)[:limit]

    if index is None:
        index = SearchIndex()
        for cand in cands:
            index.add(cand.record)

    allowed = set(unique)
    matched = {p: index.docs_for(p) & allowed for p in prefixes}
    found = set.intersection(*matched.values())
    if not found and len(prefixes) > 1:
        found = set.union(*matched.values())

    hits = []
    for cand in cands:
        item_id = cand.record.id
        if item_id not in found:
            continue
        per_field = [0] * len(FIELDS)
        first_prefixes: dict[int, list[str]] = {}
        for prefix in prefixes:
            if item_id not in matched[prefix]:
                continue
            for pos, tf in enumerate(index.field_hits(item_id, prefix)):
                if tf:
                    per_field[pos] += tf
                    first_prefixes.setdefault(pos, []).append(prefix)
        fields = [f for pos, f in enumerate(FIELDS) if per_field[pos]]
        snippet = ""
        if fields:
            first = FIELDS.index(fields[0])
            text = _field_text(cand.record, fields[0]) or ""
            snippet = _snippet(text, first_prefixes[first])
        bm25 = index.score(item_id, prefixes, matched)
        hits.append(hit(cand, bm25 * _factor(cand, on_path[item_id]), fields, snippet))
    return _ordered(hits)[:limit]


def _ordered(hits: list[Hit]) -> list[Hit]:
    # Duas passadas estáveis: score decrescente e, no empate, updated_at mais novo.
    hits.sort(key=lambda h: h.record.updated_at, reverse=True)
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits
