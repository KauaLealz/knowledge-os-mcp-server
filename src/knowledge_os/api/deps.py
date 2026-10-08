"""Dependências FastAPI: a conexão do request."""

from fastapi import Header

from knowledge_os.storage.access import resolve_connection


def get_connection_id(x_connection_id: str | None = Header(default=None)) -> str:
    """Conexão dos dados: o header X-Connection-Id ou, sem ele, a padrão do connections.json.

    422 se não há conexão configurada ou se ela está desabilitada; 404 se não existe.
    """
    return resolve_connection(x_connection_id).id
