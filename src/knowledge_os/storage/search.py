"""Busca textual em memória sobre os itens, pensada para PT-BR sem embeddings.

A recuperação depende só de palavras: a consulta do agente é reduzida ao radical aproximado de
cada termo e casada por PREFIXO contra os tokens do item (minúsculos, sem acento), então
"migração", "migrações" e "migrar" acham uns aos outros. Não há sintaxe de consulta: aspas,
asteriscos e "OR" são texto como qualquer outro.

Relevância: BM25 com pesos por campo (`FIELD_WEIGHTS`, na ordem de `FIELDS`), na mesma forma
da que o projeto já usava — a frequência de cada termo é a soma ponderada por campo e o
comprimento do documento é o total de tokens de todos os campos. Primeiro exige todos os
termos (AND); se nada casar e houver mais de um termo, aceita qualquer um (OR).

`SearchIndex` é o índice invertido, mantido incrementalmente (`add`/`remove` por item) pelo
`FileStore`, para não tokenizar tudo a cada busca.
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from knowledge_os.storage.files import ItemRecord

FIELDS = ("title", "summary", "keywords", "content")
FIELD_WEIGHTS = (6.0, 3.0, 4.0, 1.0)
_K1 = 1.2
_B = 0.75
# IDF mínimo: termo presente em quase todos os itens ainda conta um pouco (nunca negativo).
_MIN_IDF = 1e-6

_WORD = re.compile(r"[a-z0-9_]+")
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


def tokenize(text: str | None) -> list[str]:
    """Tokens de um texto do item: minúsculos e sem acento (sem radical: o prefixo cobre)."""
    if not text:
        return []
    return _WORD.findall(strip_accents(text.lower()))


def terms(query: str) -> list[str]:
    """Termos úteis da consulta: minúsculos, sem acento, sem stopwords, com radical."""
    words = _WORD.findall(strip_accents(query.lower()))
    seen: dict[str, None] = {}
    for word in words:
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
    return terms(query) or list(dict.fromkeys(_WORD.findall(strip_accents(query.lower()))))


def _field_text(record: Any, field: str) -> str | None:
    value = getattr(record, field, None)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return value


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

    def score(self, item_id: str, prefixes: list[str], matched: dict[str, set[str]]) -> float:
        """BM25 do item para os prefixos (só os que casaram contam)."""
        n_docs = len(self._docs)
        avg_length = (self._total_length / n_docs) if n_docs else 0.0
        doc = self._docs[item_id]
        length = self._lengths[item_id]
        norm = _K1 * (1 - _B + _B * (length / avg_length if avg_length else 0.0))
        total = 0.0
        for prefix in prefixes:
            if item_id not in matched[prefix]:
                continue
            freq = 0.0
            for token in self.tokens_with_prefix(prefix):
                tf = doc.get(token)
                if tf:
                    freq += sum(w * f for w, f in zip(FIELD_WEIGHTS, tf, strict=True))
            if not freq:
                continue
            n = len(matched[prefix])
            idf = math.log((n_docs - n + 0.5) / (n + 0.5))
            total += max(idf, _MIN_IDF) * (freq * (_K1 + 1)) / (freq + norm)
        return total


# --------------------------------------------------------------------------- busca


def search(
    records: Iterable[ItemRecord],
    query: str,
    limit: int,
    *,
    key: Callable[[ItemRecord], Any] | None = None,
    index: SearchIndex | None = None,
) -> list[tuple[ItemRecord, float]]:
    """Busca `query` entre `records` e devolve até `limit` pares (item, score).

    Ordem: score decrescente; empate pelo valor de `key(item)`, também decrescente (ex.:
    `lambda r: (r.importance or 0, r.confidence or 0, usos, r.updated_at)`); sem `key`, o
    empate mantém a ordem de `records`. Sem consulta, devolve todos com score 0.0 na ordem de
    `key`. `index` é o índice já mantido (o do `FileStore`); sem ele, um índice temporário é
    montado só com `records`. Itens fora do índice não são encontrados.
    """
    records = list(records)
    tie = key or (lambda _r: 0)
    prefixes = query_terms(query)
    if not prefixes:
        if query.strip():
            return []
        ordered = sorted(records, key=tie, reverse=True)
        return [(r, 0.0) for r in ordered[: max(limit, 0)]]

    if index is None:
        index = SearchIndex()
        for record in records:
            index.add(record)

    allowed = {r.id for r in records}
    matched = {p: index.docs_for(p) & allowed for p in prefixes}
    candidates = set.intersection(*matched.values())
    if not candidates and len(prefixes) > 1:
        candidates = set.union(*matched.values())
    if not candidates:
        return []

    by_id = {r.id: r for r in records}
    scored = [(by_id[i], index.score(i, prefixes, matched)) for i in candidates]
    # Ordem de entrada estável antes do sort: empate sem `key` segue `records`.
    position = {r.id: n for n, r in enumerate(records)}
    scored.sort(key=lambda pair: position[pair[0].id])
    scored.sort(key=lambda pair: (pair[1], tie(pair[0])), reverse=True)
    return scored[: max(limit, 0)]
