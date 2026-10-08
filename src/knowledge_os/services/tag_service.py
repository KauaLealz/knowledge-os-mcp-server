"""Tags e labels: etiquetas da conexão, nos itens e no `.knowledge.yaml` da raiz.

A lista é a união das criadas explicitamente (`tags`/`labels` no `.knowledge.yaml` da raiz),
das usadas em algum item e, para labels, das padrão (`brain.DEFAULT_LABELS`). O id é o
próprio nome. Remover tira do `.knowledge.yaml` e de todos os itens, numa publicação só.
"""

from __future__ import annotations

import dataclasses
import logging

from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services.brain import DEFAULT_LABELS, META_FILE, Brain, Tag, utcnow

logger = logging.getLogger(__name__)


def _clean(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 100:
        raise ValidationError("Nome deve ter entre 1 e 100 caracteres")
    return name


class TagService:
    """Operações sobre as tags (livres) da conexão (a informada ou a padrão)."""

    KIND = "tags"
    LABEL = "Tag"

    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def _listed(self, brain: Brain) -> list[Tag]:
        return brain.snapshot.tags()

    def create(self, name: str) -> Tag:
        """Cria (registra) a etiqueta. ValidationError se vazia ou duplicada."""
        name = _clean(name)
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            if any(t.name == name for t in self._listed(brain)):
                raise ValidationError(f"{self.LABEL} já existe: {name}")
            data = d.meta(META_FILE)
            removed = [n for n in data.get(f"{self.KIND}_removed") or [] if n != name]
            if self.KIND == "labels" and name in DEFAULT_LABELS:
                data[f"{self.KIND}_removed"] = removed
            else:
                data[self.KIND] = sorted({*(data.get(self.KIND) or []), name})
            if not data.get(f"{self.KIND}_removed"):
                data.pop(f"{self.KIND}_removed", None)
            d.set_meta(META_FILE, data)
            brain.commit(d, f"knowledge-os: cria {self.LABEL.lower()} {name}")
        logger.info("%s criada: %s", self.LABEL, name)
        return Tag(name, name)

    def list(self) -> list[Tag]:
        """Todas, por nome."""
        return self._listed(Brain(self._connection_id))

    def delete(self, tag_id: str) -> bool:
        """Remove a etiqueta e tira de todos os itens. NotFoundError se não existe."""
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            if not any(t.id == tag_id for t in self._listed(brain)):
                raise NotFoundError(f"{self.LABEL} não encontrada: {tag_id}")
            for record in list(d.records.values()):
                names = getattr(record, self.KIND) or []
                if tag_id in names:
                    d.put(dataclasses.replace(
                        record, **{self.KIND: [n for n in names if n != tag_id]},
                        updated_at=utcnow(),
                    ))
            data = d.meta(META_FILE)
            data[self.KIND] = [n for n in data.get(self.KIND) or [] if n != tag_id]
            if not data[self.KIND]:
                data.pop(self.KIND)
            if self.KIND == "labels" and tag_id in DEFAULT_LABELS:
                data[f"{self.KIND}_removed"] = sorted({*(data.get("labels_removed") or []),
                                                       tag_id})
            d.set_meta(META_FILE, data or None)
            brain.commit(d, f"knowledge-os: remove {self.LABEL.lower()} {tag_id}")
        logger.info("%s removida: %s", self.LABEL, tag_id)
        return True

    def set_on_item(self, item_id: str, name: str, present: bool) -> list[Tag]:
        """Põe (ou tira) a etiqueta existente `name` do item; devolve as do item."""
        brain = Brain(self._connection_id)
        with brain.editing() as d:
            record = d.require(item_id)
            if not any(t.id == name for t in self._listed(brain)):
                raise NotFoundError(f"{self.LABEL} não encontrado: {name}")
            names = set(getattr(record, self.KIND) or [])
            wanted = names | {name} if present else names - {name}
            if wanted != names:
                d.put(dataclasses.replace(record, **{self.KIND: sorted(wanted)},
                                          updated_at=utcnow()))
                brain.commit(d, f"knowledge-os: etiqueta {record.path}")
        current = getattr(brain.snapshot.require(item_id), self.KIND) or []
        return [Tag(n, n) for n in sorted(current)]
