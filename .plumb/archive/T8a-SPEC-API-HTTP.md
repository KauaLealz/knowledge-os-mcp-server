# T8a Spec: API HTTP com FastAPI — Knowledge OS

## Objetivo

Criar **camada HTTP em `src/api/`** usando FastAPI, expondo todos os services de T1-T5 como endpoints REST/JSON. Pré-requisito para a UI React (T8).

## Stack

```json
{
  "framework": "FastAPI",
  "server": "uvicorn",
  "auth": "Bearer token (simples, sem JWT complexo)",
  "cors": "CORS habilitado",
  "docs": "OpenAPI 3.0 (automático)",
  "validation": "Pydantic (já usamos)",
  "database": "SQLAlchemy 2.x (já pronto)",
  "dependencies": [
    "fastapi",
    "uvicorn",
    "python-multipart"
  ]
}
```

## Arquitetura

```
src/
├── api/
│   ├── __init__.py
│   ├── main.py (app FastAPI)
│   ├── auth.py (middleware de auth simples)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── workspace.py (GET, POST, PUT, DELETE)
│   │   ├── domain.py (GET, POST, PUT, DELETE)
│   │   ├── item.py (GET, POST, PUT, DELETE, search)
│   │   ├── relation.py (GET, POST, DELETE)
│   │   ├── tag.py (GET, POST, DELETE)
│   │   ├── label.py (GET, POST, DELETE)
│   │   ├── artifact.py (GET, POST, DELETE)
│   │   └── connection.py (GET, POST, DELETE, test)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── requests.py (Pydantic Input models)
│   │   └── responses.py (Pydantic Output models)
│   └── deps.py (dependências: get_session, verify_token)
├── main.py (continua como agora — MCP stdio)
└── ... (resto igual)

pyproject.toml
- Adicionar fastapi, uvicorn, python-multipart
```

## Endpoints

### 1. Workspaces

```
GET    /api/workspaces              → list all
POST   /api/workspaces              → create
GET    /api/workspaces/{id}         → get one
PUT    /api/workspaces/{id}         → update
DELETE /api/workspaces/{id}         → delete
GET    /api/workspaces/{id}/stats   → contagens (domains, items)
POST   /api/workspaces/{id}/export  → export ZIP
POST   /api/workspaces/{id}/import  → import ZIP
```

### 2. Domains

```
GET    /api/domains                 → list (com filtro workspace_id)
POST   /api/domains                 → create
GET    /api/domains/{id}            → get one
PUT    /api/domains/{id}            → update
DELETE /api/domains/{id}            → delete
GET    /api/domains/{id}/stats      → contagens (items)
POST   /api/domains/{id}/export     → export ZIP
```

### 3. Items

```
GET    /api/items                   → list (com filtro workspace, domain)
POST   /api/items                   → create
GET    /api/items/{id}              → get one
PUT    /api/items/{id}              → update
DELETE /api/items/{id}              → delete
GET    /api/items/search            → busca FTS (query, workspace_id, domain_id)
PUT    /api/items/{id}/confidence   → update confidence
PUT    /api/items/{id}/importance   → update importance
PUT    /api/items/{id}/memory_class → update memory class
```

### 4. Relations

```
GET    /api/relations               → list (com filtro item_id, type)
POST   /api/relations               → create
DELETE /api/relations/{id}          → delete
GET    /api/items/{id}/relations    → relações de um item (agrupadas por type)
```

### 5. Tags

```
GET    /api/tags                    → list all
POST   /api/tags                    → create
DELETE /api/tags/{id}               → delete
GET    /api/items/{id}/tags         → tags de um item
POST   /api/items/{id}/tags         → adicionar tag a item
DELETE /api/items/{id}/tags/{tag_id} → remover tag
```

### 6. Labels

```
GET    /api/labels                  → list all
POST   /api/labels                  → create
DELETE /api/labels/{id}             → delete
GET    /api/items/{id}/labels       → labels de um item
POST   /api/items/{id}/labels       → adicionar label a item
DELETE /api/items/{id}/labels/{label_id} → remover label
```

### 7. Artifacts

```
GET    /api/artifacts               → list (com filtro item_id)
POST   /api/artifacts               → upload (multipart)
GET    /api/artifacts/{id}          → download (retorna binário)
DELETE /api/artifacts/{id}          → delete
```

### 8. Connections (T7)

```
GET    /api/connections             → list all
POST   /api/connections             → create
GET    /api/connections/{id}        → get one
DELETE /api/connections/{id}        → delete
POST   /api/connections/{id}/test   → test connection
```

### 9. Health / Meta

```
GET    /                            → health check
GET    /api/openapi.json            → OpenAPI spec (automático)
GET    /docs                        → Swagger UI (automático)
GET    /redoc                       → ReDoc (automático)
```

## Autenticação

**Simples (v0.1):**
```python
# src/api/auth.py

def verify_token(token: str = Header(...)):
    # Por agora: token está em authorization header?
    # Validação: token != "" (depois JWT real em v0.2)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    return token
```

**Uso nos endpoints:**
```python
@router.get("/api/workspaces")
def list_workspaces(token: str = Depends(verify_token)):
    # token só para validar que cliente mandou algo
    # Permissionamento real em v0.2
    ...
```

## Request/Response

### Exemplo: Create Item

**Request:**
```json
{
  "workspace_id": "ws_123",
  "domain_id": "dom_456",
  "type": "knowledge",
  "memory_class": "longterm",
  "title": "ConditionalOnProperty",
  "summary": "Spring annotation para condicional",
  "content": "# Markdown content...",
  "confidence": 90,
  "importance": 8,
  "tags": ["spring", "java", "annotation"],
  "labels": ["official"]
}
```

**Response (201):**
```json
{
  "id": "item_789",
  "workspace_id": "ws_123",
  "domain_id": "dom_456",
  "type": "knowledge",
  "memory_class": "longterm",
  "title": "ConditionalOnProperty",
  "summary": "Spring annotation para condicional",
  "content": "# Markdown content...",
  "confidence": 90,
  "importance": 8,
  "tags": ["spring", "java", "annotation"],
  "labels": ["official"],
  "access_count": 0,
  "created_at": "2026-10-02T14:30:00Z",
  "updated_at": "2026-10-02T14:30:00Z",
  "last_accessed": null
}
```

### Exemplo: Search Items

**Request:**
```
GET /api/items/search?query=conditional&workspace_id=ws_123&domain_id=dom_456
```

**Response:**
```json
{
  "query": "conditional",
  "total": 3,
  "results": [
    {
      "id": "item_789",
      "title": "ConditionalOnProperty",
      "summary": "Spring annotation...",
      "match_score": 0.95,
      "memory_class": "longterm"
    },
    ...
  ],
  "took_ms": 42
}
```

## Estrutura de Arquivos

### `src/api/main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import workspace, domain, item, relation, tag, label, artifact, connection

app = FastAPI(
    title="Knowledge OS API",
    version="0.1.0",
    description="REST API para Knowledge OS MCP",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/openapi.json"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # v0.1: permissivo; v0.2: lista de hosts
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/")
def health():
    return {"status": "ok", "version": "0.1.0"}

# Routers
app.include_router(workspace.router, prefix="/api", tags=["workspaces"])
app.include_router(domain.router, prefix="/api", tags=["domains"])
app.include_router(item.router, prefix="/api", tags=["items"])
app.include_router(relation.router, prefix="/api", tags=["relations"])
app.include_router(tag.router, prefix="/api", tags=["tags"])
app.include_router(label.router, prefix="/api", tags=["labels"])
app.include_router(artifact.router, prefix="/api", tags=["artifacts"])
app.include_router(connection.router, prefix="/api", tags=["connections"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### `src/api/auth.py`

```python
from fastapi import Header, HTTPException

def verify_token(authorization: str = Header(...)):
    """Validação simples: token deve estar presente."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    token = authorization.replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    return token
```

### `src/api/routes/workspace.py` (exemplo)

```python
from fastapi import APIRouter, Depends, HTTPException
from src.api.auth import verify_token
from src.services.workspace_service import WorkspaceService
from src.api.schemas import responses

router = APIRouter()

@router.get("/workspaces")
def list_workspaces(token: str = Depends(verify_token)):
    service = WorkspaceService(session)  # session via Depends(get_session)
    items = service.list()
    return [responses.WorkspaceResponse.from_orm(w) for w in items]

@router.post("/workspaces")
def create_workspace(req: requests.WorkspaceCreate, token: str = Depends(verify_token)):
    service = WorkspaceService(session)
    ws = service.create(req.name, req.description)
    return responses.WorkspaceResponse.from_orm(ws)

# ... GET, PUT, DELETE, export, import
```

### `src/api/schemas/requests.py`

```python
from pydantic import BaseModel

class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None

class ItemCreate(BaseModel):
    workspace_id: str
    domain_id: str
    type: str
    memory_class: str
    title: str
    summary: str
    content: str
    confidence: int | None = None
    importance: int | None = None
    tags: list[str] = []
    labels: list[str] = []

# ... demais schemas
```

### `src/api/schemas/responses.py`

```python
from pydantic import BaseModel
from datetime import datetime

class WorkspaceResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2

# ... demais schemas
```

### `src/api/deps.py`

```python
from sqlalchemy.orm import Session
from src.db.session import get_session

async def get_session_dep():
    """Dependency para obter session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()
```

## Testes (T8a)

```bash
tests/api/
├── conftest.py (fixtures com client FastAPI)
├── test_workspaces.py
├── test_domains.py
├── test_items.py
├── test_relations.py
├── test_tags.py
├── test_labels.py
├── test_artifacts.py
└── test_auth.py

# Exemplo: test_workspaces.py
def test_list_workspaces(client, token):
    resp = client.get("/api/workspaces", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

def test_create_workspace(client, token):
    resp = client.post(
        "/api/workspaces",
        json={"name": "Test", "description": "Desc"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test"
```

## Integração com `src/main.py` (MCP)

**Ambos coexistem:**
- `src/main.py` → `mcp.run()` (FastMCP, stdio) — continua igual
- `src/api/main.py` → `uvicorn` (FastAPI, HTTP) — novo

**Rodagem:**
```bash
# Terminal 1: MCP (stdio)
python src/main.py

# Terminal 2: HTTP API
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Ou Docker
docker run -p 8000:8000 knowledge-os-api
```

## pyproject.toml

```toml
[tool.poetry.dependencies]
# ... existente ...
fastapi = "^0.110.0"
uvicorn = { version = "^0.28.0", extras = ["standard"] }
python-multipart = "^0.0.6"

[tool.poetry.group.dev.dependencies]
# ... existente ...
httpx = "^0.26.0"  # para testes do FastAPI
```

## Critério de Sucesso (T8a)

✓ `pytest tests/api/ -v` → 50+ testes passed
✓ Todos os 8 endpoints grupos funcionam (CRUD)
✓ Auth middleware valida token
✓ OpenAPI spec gerado (GET /api/openapi.json)
✓ CORS funcionando
✓ Swagger UI acessível (GET /docs)
✓ Integração com services T1-T5 completa
✓ Retorna JSON válido (Pydantic validation)
✓ `ruff check src/api/` clean
✓ Zero breaking changes com T1-T5 (services intactos)

## Timeline

- **Dia 1:** Setup FastAPI, auth, rotas skeleton
- **Dia 1-2:** Implementar CRUD (workspace, domain, item, relation, tag, label)
- **Dia 2:** Artifact upload/download, connection, search
- **Dia 2:** Testes + OpenAPI validação
- **Total: 1-2 dias**

## Próximo

Após T8a pronto: **T8 retoma** com API HTTP funcionando 🚀

---

**Dependências:**
- T1-T5 (services) ✅
- T7 (connection model) ⏳ (parcial: usamos default connection)

**Paralelo com:**
- T6 (testes + docs)
- T7 (multi-db)

**Status:** Pronto para implementação após aprovação
