"""App FastAPI do Knowledge OS: camada HTTP sobre os services."""

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import (
    artifact,
    connection,
    domain,
    item,
    label,
    relation,
    tag,
    workspace,
)
from src.exceptions import DatabaseError, NotFoundError, ValidationError

VERSION = "0.1.0"

app = FastAPI(
    title="Knowledge OS API",
    version=VERSION,
    description="REST API para Knowledge OS MCP",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/openapi.json",
)

# Sem login: o servidor é local (127.0.0.1). Sem CORS: a UI é servida pela mesma origem.
# TrustedHost barra DNS rebinding (Host forjado); "testserver" é o host do TestClient.
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def _same_origin_writes(request: Request, call_next):
    """Recusa escrita vinda de outra página: o navegador manda `Origin` e ele deve ser o do Host.

    Sem `Origin` (curl, scripts, TestClient) a requisição passa: só o navegador é o vetor.
    """
    origin = request.headers.get("origin")
    if request.method in _WRITE_METHODS and origin is not None:
        if origin == "null" or urlsplit(origin).netloc != request.headers.get("host", ""):
            return JSONResponse(status_code=403, content={"detail": "Origin não permitida"})
    return await call_next(request)


@app.exception_handler(NotFoundError)
async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def _validation(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(DatabaseError)
async def _database(_: Request, exc: DatabaseError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}


for _module, _tag in (
    (workspace, "workspaces"),
    (domain, "domains"),
    (item, "items"),
    (relation, "relations"),
    (tag, "tags"),
    (label, "labels"),
    (artifact, "artifacts"),
    (connection, "connections"),
):
    app.include_router(_module.router, prefix="/api", tags=[_tag])

# UI estática (Alpine + ES modules, libs via CDN, sem build). Em /ui porque "/" já é o health check.
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")

