"""App FastAPI do Knowledge OS: camada HTTP sobre os services."""

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from knowledge_os import __version__
from knowledge_os.api.routes import (
    connection,
    fs,
    item,
    label,
    project,
    relation,
    tag,
    workspace,
)
from knowledge_os.exceptions import NotFoundError, StorageError, ValidationError

app = FastAPI(
    title="Knowledge OS API",
    version=__version__,
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


_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    # Tudo servido daqui (sem CDN). 'unsafe-eval': o Alpine avalia as expressões dos atributos;
    # style 'unsafe-inline': atributos style do HTML.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    ),
}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    if request.url.path.startswith("/ui"):
        # Módulos ES sem build: sem isso o navegador mistura versões em cache depois de uma
        # atualização (import de export inexistente = tela preta). Revalida por ETag (304).
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(NotFoundError)
async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def _validation(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(StorageError)
async def _storage(_: Request, exc: StorageError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


for _module, _tag in (
    (workspace, "workspaces"),
    (project, "projects"),
    (item, "items"),
    (relation, "relations"),
    (tag, "tags"),
    (label, "labels"),
    (connection, "connections"),
    (fs, "fs"),
):
    app.include_router(_module.router, prefix="/api", tags=[_tag])

# UI estática (Alpine + ES modules, libs via CDN, sem build). Em /ui porque "/" já é o health check.
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")

