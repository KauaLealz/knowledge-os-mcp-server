"""Autenticação por Bearer token: um token por start da UI, comparado em tempo constante."""

import hmac

from fastapi import Header, HTTPException

_token: str | None = None


def set_token(token: str | None) -> None:
    """Define o token válido (None = nenhum: a API recusa todas as requisições)."""
    global _token
    _token = token or None


def verify_token(authorization: str | None = Header(default=None)) -> str:
    """Exige `Authorization: Bearer <token>` igual ao token configurado. Fail closed."""
    expected = _token
    provided = ""
    if authorization and authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ").strip()
    # compare_digest sempre roda, para não variar o tempo conforme o motivo da recusa
    ok = hmac.compare_digest(provided.encode(), (expected or "").encode())
    if expected is None or not provided or not ok:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return provided
