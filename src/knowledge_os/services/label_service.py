"""Label service: a lista controlada de labels (padrão + criadas), como as tags."""

from __future__ import annotations

from knowledge_os.services.brain import Brain, Label
from knowledge_os.services.tag_service import TagService


class LabelService(TagService):
    """Operações sobre labels; as padrão (`brain.DEFAULT_LABELS`) existem sem item."""

    KIND = "labels"
    LABEL = "Label"

    def _listed(self, brain: Brain) -> list[Label]:
        return brain.snapshot.labels()
