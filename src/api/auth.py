"""Autenticação simples por Bearer token (v0.1: só exige que o token exista)."""

from fastapi import Header, HTTPException


def verify_token(authorization: str | None = Header(default=None)) -> str:
    """Exige `Authorization: Bearer <token>` com token não vazio. Retorna o token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    return token
