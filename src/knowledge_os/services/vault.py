"""Cifra dos valores de segredo: Fernet com uma chave mestra que nunca vai para o banco.

A chave vem de KNOWLEDGE_OS_VAULT_KEY ou do keyring do sistema (no Windows, o Gerenciador de
Credenciais). Sem ela, o arquivo do banco (e os backups) guardam só texto cifrado.
"""

import os
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from knowledge_os.exceptions import ValidationError

ENV_KEY = "KNOWLEDGE_OS_VAULT_KEY"
KEYRING_SERVICE = "knowledge-os"
KEYRING_NAME = "vault-master-key"
# Marca, no home, que uma chave já foi criada: a chave vale para todas as conexões, então a
# ausência de valores num banco não prova que nenhuma chave existiu.
MARKER_NAME = "vault.created"
WAIT_OTHER_S = 5.0


def _marker() -> Path:
    from knowledge_os import config

    return config.KNOWLEDGE_HOME / MARKER_NAME


def _keyring_get() -> str | None:
    import keyring

    return keyring.get_password(KEYRING_SERVICE, KEYRING_NAME)


def _keyring_set(key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_NAME, key)


def _stored_key() -> str | None:
    env = os.environ.get(ENV_KEY, "").strip()
    if env:
        return env
    try:
        return _keyring_get()
    except Exception as exc:  # noqa: BLE001 - backend ausente ou bloqueado
        raise ValidationError(
            f"Não consegui ler a chave mestra no keyring do sistema ({type(exc).__name__}). "
            f"Defina {ENV_KEY} ou habilite o keyring."
        ) from None


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise ValidationError(f"Chave mestra inválida (em {ENV_KEY} ou no keyring)") from None


def master(create: bool) -> Fernet:
    """Fernet da chave mestra. `create`: gera e guarda no keyring se ainda não existe.

    Quem chama só passa create=True quando não há nenhum valor cifrado: gerar uma chave nova
    por cima deixaria os valores antigos ilegíveis.
    """
    key = _stored_key()
    if key:
        return _fernet(key)
    lost = ValidationError(
        "A chave mestra dos segredos sumiu (keyring e "
        f"{ENV_KEY} vazios), mas ela já foi criada antes. Restaure a chave; não vou gerar "
        "outra por cima, porque os valores cifrados com ela ficariam ilegíveis."
    )
    marker = _marker()
    if not create or marker.exists():
        raise lost
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # só um processo gera
    except FileExistsError:
        deadline = time.monotonic() + WAIT_OTHER_S
        while time.monotonic() < deadline:  # outro processo está gerando agora
            key = _stored_key()
            if key:
                return _fernet(key)
            time.sleep(0.1)
        raise lost from None
    os.close(fd)
    key = Fernet.generate_key().decode()
    try:
        _keyring_set(key)
    except Exception as exc:  # noqa: BLE001
        marker.unlink(missing_ok=True)
        raise ValidationError(
            f"Não consegui guardar a chave mestra no keyring ({type(exc).__name__}). "
            f"Defina {ENV_KEY} com uma chave Fernet."
        ) from None
    if _stored_key() != key:
        marker.unlink(missing_ok=True)
        raise ValidationError("O keyring não devolveu a chave mestra que acabei de guardar")
    return _fernet(key)


def encrypt(value: str, bound_to: str, create: bool = True) -> str:
    """Cifra `bound_to` + NUL + valor: trocar o texto cifrado de linha não troca o segredo."""
    return master(create).encrypt(f"{bound_to}\0{value}".encode()).decode()


def decrypt(token: str, bound_to: str) -> str:
    try:
        plain = master(create=False).decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValidationError(
            "A chave mestra atual não abre este valor (a chave foi trocada?). Preencha o "
            "segredo de novo pela UI."
        ) from None
    owner, sep, value = plain.partition("\0")
    if not sep or owner != bound_to:
        raise ValidationError(
            "Este valor cifrado pertence a outro segredo (linha trocada no banco). Preencha o "
            "segredo de novo pela UI."
        )
    return value
