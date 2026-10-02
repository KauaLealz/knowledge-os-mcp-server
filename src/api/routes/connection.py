"""Rotas de connections (a senha nunca é exposta)."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from src.api.auth import verify_token
from src.api.deps import get_session_dep
from src.api.schemas.requests import ConnectionCreate
from src.api.schemas.responses import ConnectionResponse, ConnectionTestResponse
from src.exceptions import NotFoundError
from src.services._common import connection_to_dict
from src.services.connection_service import ConnectionService

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/connections", response_model=list[ConnectionResponse])
def list_connections(session: Session = Depends(get_session_dep)):
    return [connection_to_dict(c) for c in ConnectionService(session).list()]


@router.post("/connections", status_code=status.HTTP_201_CREATED, response_model=ConnectionResponse)
def create_connection(req: ConnectionCreate, session: Session = Depends(get_session_dep)):
    conn = ConnectionService(session).create(req.name, req.db_type, req.db_url, test=True)
    return connection_to_dict(conn)


@router.get("/connections/{id}", response_model=ConnectionResponse)
def get_connection(id: str, session: Session = Depends(get_session_dep)):
    return connection_to_dict(ConnectionService(session).get(id))


@router.delete("/connections/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(id: str, session: Session = Depends(get_session_dep)) -> Response:
    if not ConnectionService(session).delete(id):
        raise NotFoundError(f"Conexão não encontrada: {id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{id}/test", response_model=ConnectionTestResponse)
def test_connection(id: str, session: Session = Depends(get_session_dep)):
    return ConnectionService(session).test(id)
