"""Rotas de connections sobre o connections.json. A senha é só de escrita: nunca volta."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from knowledge_os.api.deps import get_catalog_session_dep
from knowledge_os.api.schemas.requests import ConnectionCreate, ConnectionUpdate
from knowledge_os.api.schemas.responses import (
    ConnectionResponse,
    ConnectionTestResponse,
    SchemaSyncResponse,
)
from knowledge_os.db.models import DEFAULT_CONNECTION_ID, Connection
from knowledge_os.exceptions import NotFoundError
from knowledge_os.services.connection_service import ConnectionService


class _SafeRoute(APIRoute):
    """422 de validação sem o `input` recebido: o corpo pode trazer senha ou URL com senha."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                detail = [
                    {"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]}
                    for e in exc.errors()
                ]
                return JSONResponse(status_code=422, content={"detail": detail})

        return handler


router = APIRouter(route_class=_SafeRoute)


def _view(conn: Connection) -> dict[str, Any]:
    """Serializa a conexão para a API: repositório git, sem URL do índice."""
    return {
        "id": conn.id,
        "name": conn.name,
        "path": getattr(conn, "path", None),
        "remote_url": getattr(conn, "remote_url", None),
        "review_mode": getattr(conn, "review_mode", "direct"),
        "enabled": bool(conn.is_active),
        "is_default": bool(getattr(conn, "is_default", False)),
        "is_catalog": conn.id == DEFAULT_CONNECTION_ID,
        "last_test": getattr(conn, "last_test", None),
        "created_at": conn.created_at,
    }


@router.get("/connections", response_model=list[ConnectionResponse])
def list_connections(session: Session = Depends(get_catalog_session_dep)):
    return [_view(c) for c in ConnectionService(session).list()]


@router.post("/connections", status_code=status.HTTP_201_CREATED, response_model=ConnectionResponse)
def create_connection(req: ConnectionCreate, session: Session = Depends(get_catalog_session_dep)):
    conn = ConnectionService(session).create(
        req.name,
        req.path,
        remote_url=req.remote_url,
        review_mode=req.review_mode,
        enabled=req.enabled,
    )
    return _view(conn)


@router.get("/connections/{id}", response_model=ConnectionResponse)
def get_connection(id: str, session: Session = Depends(get_catalog_session_dep)):
    return _view(ConnectionService(session).get(id))


@router.patch("/connections/{id}", response_model=ConnectionResponse)
def update_connection(
    id: str, req: ConnectionUpdate, session: Session = Depends(get_catalog_session_dep)
):
    fields = req.model_dump(exclude_unset=True)
    if "enabled" in fields:
        fields["is_active"] = fields.pop("enabled")
    if "name" in fields and fields["name"] is None:
        del fields["name"]
    return _view(ConnectionService(session).update(id, **fields))


@router.delete("/connections/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(id: str, session: Session = Depends(get_catalog_session_dep)) -> Response:
    if not ConnectionService(session).delete(id):
        raise NotFoundError(f"Conexão não encontrada: {id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{id}/test", response_model=ConnectionTestResponse)
def test_connection(id: str, session: Session = Depends(get_catalog_session_dep)):
    return ConnectionService(session).test(id)


@router.put("/connections/{id}/default", response_model=ConnectionResponse)
def set_default_connection(id: str, session: Session = Depends(get_catalog_session_dep)):
    return _view(ConnectionService(session).set_default(id))


@router.post("/connections/{id}/schema-sync", response_model=SchemaSyncResponse)
def sync_connection_schema(
    id: str, dry_run: bool = True, session: Session = Depends(get_catalog_session_dep)
):
    return ConnectionService(session).sync_schema(id, dry_run=dry_run)
