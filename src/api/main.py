"""App FastAPI do Knowledge OS: camada HTTP sobre os services."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # v0.1: permissivo; v0.2: lista de hosts
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

# UI estática (Alpine + Tailwind via CDN). Em /ui porque "/" já é o health check.
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
