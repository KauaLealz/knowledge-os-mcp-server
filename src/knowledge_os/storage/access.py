"""Acesso às conexões: qual conexão, qual pasta, qual `FileStore` e qual repositório git.

Uma conexão é uma pasta local (repositório git) cadastrada em `connections.json`. Não existe
conexão implícita: sem nenhuma cadastrada (ou sem uma padrão), toda operação que precisa de uma
levanta `NoConnectionError` com a mesma mensagem, que diz como criar.

`get_store` devolve o `FileStore` da conexão (um por conexão e pasta, guardado em memória),
já atualizado com o que mudou na pasta. `lock_for` dá a trava da conexão neste processo: a UI
(numa thread) e o MCP dividem o mesmo `FileStore`; `folder_lock` é a trava entre processos
das escritas na mesma pasta.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import knowledge_os.config as config
from knowledge_os.config import (
    NO_CONNECTION_MESSAGE,
    ConfigManager,
    ConnectionConfig,
    ConnectionsFile,
    config_error,
)
from knowledge_os.exceptions import (
    NoConnectionError,
    NotFoundError,
    StorageError,
    ValidationError,
)
from knowledge_os.services.git_repo_service import GitRepoService
from knowledge_os.storage.files import FileStore

LOCK_TIMEOUT_S = 60.0  # espera máxima pela gravação de outro processo
LOCK_STALE_S = 300.0  # trava mais velha que isso: o processo dono morreu

_registry_lock = threading.Lock()
_stores: dict[str, tuple[Path, FileStore]] = {}
_locks: dict[str, threading.RLock] = {}
_known_repos: set[Path] = set()


def load_connections() -> ConnectionsFile:
    """connections.json do home (relido a cada chamada); erro sem ecoar valores."""
    try:
        return ConfigManager.load()
    except Exception as exc:
        raise config_error(exc) from None


def default_connection_id() -> str | None:
    """Id da conexão padrão, ou None se não há nenhuma."""
    return load_connections().default


def resolve_connection(connection_id: str | None = None) -> ConnectionConfig:
    """Conexão habilitada pelo id (ou nome); sem id, a padrão.

    `NoConnectionError` se não há conexão padrão; `NotFoundError` se o id não existe;
    `ValidationError` se a conexão está desativada.
    """
    config = load_connections()
    wanted = (connection_id or "").strip()
    if not wanted:
        if not config.default:
            raise NoConnectionError(NO_CONNECTION_MESSAGE)
        wanted = config.default
    conn = next((c for c in config.connections if c.id == wanted), None)
    if conn is None:
        conn = next((c for c in config.connections if c.name == wanted), None)
    if conn is None:
        if not config.connections:
            raise NoConnectionError(NO_CONNECTION_MESSAGE)
        raise NotFoundError(f"Conexão não encontrada: {wanted}")
    if not conn.enabled:
        raise ValidationError(f"Conexão inativa: {conn.name}")
    return conn


def lock_for(connection_id: str) -> threading.RLock:
    """Trava (reentrante) das leituras e escritas da conexão neste processo."""
    with _registry_lock:
        lock = _locks.get(connection_id)
        if lock is None:
            lock = _locks[connection_id] = threading.RLock()
        return lock


def store_for(conn: ConnectionConfig) -> FileStore:
    """`FileStore` da pasta da conexão, atualizado (`refresh`) com o que mudou nela."""
    root = conn.clone_path()
    with lock_for(conn.id):
        with _registry_lock:
            cached = _stores.get(conn.id)
        if cached is not None and cached[0] == root:
            store = cached[1]
            store.refresh()
            return store
        store = FileStore(root)
        with _registry_lock:
            _stores[conn.id] = (root, store)
        return store


def get_store(connection_id: str | None = None) -> FileStore:
    """`FileStore` da conexão informada (ou da padrão), já atualizado."""
    return store_for(resolve_connection(connection_id))


def forget(connection_id: str) -> None:
    """Esquece o `FileStore` guardado da conexão (removida ou com a pasta trocada)."""
    with _registry_lock:
        _stores.pop(connection_id, None)


@contextmanager
def folder_lock(root: Path, timeout_s: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """Trava entre processos das escritas numa pasta (MCP de dois clientes + UI + CLI).

    Arquivo criado com O_EXCL em `<home>/locks/`; fora do repositório, para não aparecer no
    git. Uma trava mais velha que `LOCK_STALE_S` é de um processo que morreu e é retomada.
    """
    digest = hashlib.sha1(str(root.resolve()).lower().encode()).hexdigest()  # noqa: S324
    path = Path(config.KNOWLEDGE_HOME) / "locks" / f"{digest}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    wait = 0.01
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                continue  # soltou entre a tentativa e o stat
            if age > LOCK_STALE_S:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() + wait > deadline:
                raise StorageError(
                    "Outra gravação nesta conexão não terminou a tempo. Tente de novo em "
                    "instantes."
                ) from None
            time.sleep(wait)
            wait = min(wait * 2, 0.2)
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        break
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def git_for(conn: ConnectionConfig) -> GitRepoService:
    """Repositório git da conexão, já clonado/inicializado (uma vez por processo e pasta)."""
    git = GitRepoService(conn.clone_path(), conn.remote_url, conn.review_mode)
    root = conn.clone_path()
    if root not in _known_repos or not (root / ".git").exists():
        git.ensure_clone()
        _known_repos.add(root)
    return git
