"""Helpers compartilhados pelas rotas."""

from typing import TypeVar

from sqlalchemy.orm import Session

from src.exceptions import NotFoundError

T = TypeVar("T")


def get_or_404(session: Session, model: type[T], obj_id: str, label: str) -> T:
    """Busca por id ou levanta NotFoundError (vira 404)."""
    obj = session.get(model, obj_id)
    if obj is None:
        raise NotFoundError(f"{label} não encontrado: {obj_id}")
    return obj
