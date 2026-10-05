"""Barra segredos antes de entrarem na base.

O segundo cérebro vira contexto de toda sessão: um segredo gravado num item vaza para
todo projeto e todo agente que o ler. A mensagem de erro diz o tipo e o campo, nunca o
valor encontrado.
"""

import re

from src.exceptions import ValidationError

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chave privada", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY")),
    ("chave de acesso AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "token do GitHub",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    ),
    ("token do Slack", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("chave de API do Google", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("chave de API (sk-)", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    (
        "credencial atribuída",
        re.compile(
            r"(?i)\b(?:password|passwd|senha|secret|api[_-]?key|access[_-]?token|client[_-]?secret)"
            r"\s*[:=]\s*['\"]?(?!<|\$\{|\{\{|\*{3}|x{3,}|\.\.\.)[^\s'\"<>]{8,}"
        ),
    ),
    (
        "URL com senha",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:(?!\*{3}|<)[^\s@/]{4,}@"),
    ),
)


def find_secret(text: str | None) -> str | None:
    """Tipo do primeiro segredo encontrado no texto, ou None."""
    if not text:
        return None
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            return kind
    return None


def ensure_no_secrets(**fields: str | None) -> None:
    """Levanta ValidationError se algum campo contém algo com cara de segredo."""
    for name, value in fields.items():
        kind = find_secret(value)
        if kind:
            raise ValidationError(
                f"'{name}' parece conter um segredo ({kind}). Segredos não entram na base: "
                "guarde só onde o valor fica (ex.: variável de ambiente) e descreva sem o valor."
            )
