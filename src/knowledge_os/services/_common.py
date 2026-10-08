"""Helpers compartilhados pelos services."""

from pathlib import Path

import knowledge_os.config as config
from knowledge_os.exceptions import ValidationError


def refuse_home_source(path: Path) -> None:
    """ValidationError se o caminho (resolvido, seguindo symlinks) está dentro do home de dados.

    Protege connections.json e o estado local de virar pasta de uma connection nova. O home é
    lido na chamada.
    """
    resolved = path.resolve()
    if resolved.is_relative_to(config.KNOWLEDGE_HOME.resolve()):
        raise ValidationError("Caminho dentro do home de dados não é permitido")

