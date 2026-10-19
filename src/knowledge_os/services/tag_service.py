"""Tags gerenciadas: vocabulário no `.knowledge.yaml` da raiz + as tags usadas nos itens.

A lista é a união do vocabulário (`tags: [...]`, inclusive tags sem item) com as usadas em algum
item (`Snapshot.tags`). Nomes em kebab-case minúsculo (`model.normalize_tag`). Renomear e
remover regravam os itens e o vocabulário numa publicação só; renomear para um nome que já
existe mescla. Tag nova vinda do `item_save` entra no vocabulário por `ensure_in_draft`, com
aviso e sugestão de uma parecida.
"""

from __future__ import annotations

import dataclasses
import difflib
import logging
from typing import Any

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.model import normalize_tag
from knowledge_os.services.brain import META_FILE, Brain, Draft, Snapshot, Tag, utcnow
from knowledge_os.services.relation_service import review_fields

logger = logging.getLogger(__name__)

SIMILAR_CUTOFF = 0.8


def _vocabulary(draft: Draft) -> set[str]:
    return {str(n) for n in draft.meta(META_FILE).get("tags") or []}


def _write_vocabulary(draft: Draft, names: set[str]) -> None:
    data = draft.meta(META_FILE)
    if names:
        data["tags"] = sorted(names)
    else:
        data.pop("tags", None)
    draft.set_meta(META_FILE, data or None)


def _counts(snapshot: Snapshot) -> dict[str, int]:
    counts = {t.name: 0 for t in snapshot.tags()}
    for record in snapshot.records.values():
        for name in set(record.tags or []):
            counts[name] = counts.get(name, 0) + 1
    return counts


def _exact(name: str, known: dict[str, int] | set[str]) -> str:
    """O nome como existe: tags antigas fora do padrão casam pelo texto exato; senão normaliza."""
    return name if name in known else normalize_tag(name)


def _names(names: Any) -> list[str]:
    if not isinstance(names, list) or not names:
        raise ValidationError("names deve ser uma lista não vazia de nomes de tag")
    return names


class TagService:
    """Operações sobre as tags da conexão (a informada ou a padrão)."""

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def list(self) -> list[dict]:
        """`[{name, count}]` por nome; inclui as do vocabulário sem item (`count: 0`)."""
        counts = _counts(Brain(self._connection_id).snapshot)
        return [{"name": n, "count": counts[n]} for n in sorted(counts)]

    def create(self, names: list[str]) -> dict:
        """Registra as tags no vocabulário. `{created, existing}` (nomes já normalizados)."""
        wanted = list(dict.fromkeys(normalize_tag(n) for n in _names(names)))
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            known = {t.name for t in d.tags()}
            created = [n for n in wanted if n not in known]
            existing = [n for n in wanted if n in known]
            extra: dict[str, Any] = {}
            if created:
                _write_vocabulary(d, _vocabulary(d) | set(created))
                extra = review_fields(brain.commit(d, "knowledge-os: cria tag(s) "
                                                      + ", ".join(created)))
        logger.info("Tags criadas: %s", created)
        return {"created": created, "existing": existing, **extra}

    def update(self, name: str, new_name: str) -> dict:
        """Renomeia `name` em todos os itens e no vocabulário (1 commit). Se `new_name` já
        existe, mescla. `{renamed: itens regravados, merged: bool}`. NotFoundError se `name`
        não existe."""
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            counts = _counts(d)
            old = _exact(name, counts)
            if old not in counts:
                raise NotFoundError(f"Tag não encontrada: {name}. Existentes: "
                                    f"{', '.join(sorted(counts)) or '(nenhuma)'}")
            new = normalize_tag(new_name)
            if new == old:
                return {"renamed": 0, "merged": False}
            merged = new in counts
            renamed = 0
            for record in list(d.records.values()):
                tags = list(record.tags or [])
                if old not in tags:
                    continue
                swapped = list(dict.fromkeys(new if t == old else t for t in tags))
                d.put(dataclasses.replace(record, tags=swapped, updated_at=utcnow()))
                renamed += 1
            _write_vocabulary(d, (_vocabulary(d) - {old}) | {new})
            extra = review_fields(brain.commit(d, f"knowledge-os: renomeia tag {old} -> {new}"))
        logger.info("Tag renomeada: %s -> %s (%d itens, mesclada=%s)", old, new, renamed, merged)
        return {"renamed": renamed, "merged": merged, **extra}

    def delete(self, names: list[str], confirm: bool = False) -> dict:
        """Sem `confirm`, prévia `{status: "preview", tags: [{name, items}]}`; com `confirm=True`
        tira as tags dos itens e do vocabulário (1 commit) e devolve `{status: "deleted", ...}`."""
        wanted = list(dict.fromkeys(_names(names)))
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            counts = _counts(d)
            resolved = [_exact(n, counts) for n in wanted]
            missing = [n for n, r in zip(wanted, resolved, strict=True) if r not in counts]
            if missing:
                raise NotFoundError(f"Tag não encontrada: {', '.join(missing)}. Existentes: "
                                    f"{', '.join(sorted(counts)) or '(nenhuma)'}")
            summary = [{"name": r, "items": counts[r]} for r in dict.fromkeys(resolved)]
            if not confirm:
                return {"status": "preview", "tags": summary}
            gone = {t["name"] for t in summary}
            for record in list(d.records.values()):
                tags = list(record.tags or [])
                if gone.intersection(tags):
                    d.put(dataclasses.replace(
                        record, tags=[t for t in tags if t not in gone], updated_at=utcnow()))
            _write_vocabulary(d, _vocabulary(d) - gone)
            extra = review_fields(brain.commit(
                d, "knowledge-os: remove tag(s) " + ", ".join(sorted(gone))))
        logger.info("Tags removidas: %s", sorted(gone))
        return {"status": "deleted", "tags": summary, **extra}

    @staticmethod
    def ensure_in_draft(draft: Draft, names: list[str]) -> list[str]:
        """Põe no vocabulário (do rascunho) as tags que ainda não existem e devolve os avisos
        (`tag nova 'x' criada; existe parecida: 'y'`). Existente = o que já havia antes do
        rascunho ou foi criado nele; quem chama publica com o `commit` do rascunho."""
        base = draft._base  # as tags que o item em edição acabou de citar não contam
        known = {t.name for t in base.tags()} | _vocabulary(draft)
        warnings: list[str] = []
        added: set[str] = set()
        for raw in names:
            name = normalize_tag(raw)
            if name in known:
                continue
            similar = difflib.get_close_matches(name, sorted(known), n=1,
                                                cutoff=SIMILAR_CUTOFF)
            warning = f"tag nova '{name}' criada"
            if similar:
                warning += f"; existe parecida: '{similar[0]}'"
            warnings.append(warning)
            known.add(name)
            added.add(name)
        if added:
            _write_vocabulary(draft, _vocabulary(draft) | added)
        return warnings

    def set_on_item(self, item_id: str, name: str, present: bool) -> list[Tag]:
        """Põe (ou tira) a tag existente `name` do item; devolve as do item (API)."""
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            record = d.require(item_id)
            counts = _counts(d)
            tag = _exact(name, counts)
            if tag not in counts:
                raise NotFoundError(f"Tag não encontrada: {name}")
            current = set(record.tags or [])
            wanted = current | {tag} if present else current - {tag}
            if wanted != current:
                d.put(dataclasses.replace(record, tags=sorted(wanted), updated_at=utcnow()))
                brain.commit(d, f"knowledge-os: tag {record.path}")
        return [Tag(n, n) for n in sorted(brain.snapshot.require(item_id).tags or [])]
