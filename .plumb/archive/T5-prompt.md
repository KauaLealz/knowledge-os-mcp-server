# T5 Prompt — Artifacts + Main Server (Pronto para Despacho)

## Task T5: Artifacts e Servidor Principal — mcp-knowledge-os

### Contexto
Projeto: MCP Knowledge OS. Trilha: Profunda.
Commits: 462d95f (T2), antes: T1 com 9 testes
Branch: feature/mcp-knowledge-os
Status: T1 ✅, T2 ✅, T3 ✅ (concluído), T4 ✅ (concluído)

Todas as services (workspace, domain, item, relation, memory, tag, label) estão prontas.
Todas as schemas estão prontas.
Todos os tools parciais estão criados — faltam artifact tools e import/export completo.

Stack: FastMCP, SQLAlchemy 2.x, Pydantic v2, SQLite+FTS5.

### Objective
Implementar: (1) artifact service + tools, (2) import/export service completo, (3) workspace_import / domain_import implementados, (4) main.py final com todos os tools registrados.

### Deliverables (em ordem)

**S1. src/services/artifact_service.py**
- `ArtifactService` com métodos:
  - `attach(item_id: str, file_path: str) -> Artifact` — copia arquivo para ARTIFACTS_DIR, cria registro
  - `list(item_id: str) -> list[Artifact]` — lista artifacts de um item
  - `get(artifact_id: str) -> tuple[Artifact, bytes]` — retorna metadados + conteúdo do arquivo

Arquivo vai para `ARTIFACTS_DIR` com nome único (uuid).

**S2. src/services/import_export_service.py**
- `ImportExportService` com métodos:
  - `export_workspace(workspace_id: str) -> bytes` — retorna ZIP com manifest.json, workspace.json, domains/, items/, artifacts/, relations/
  - `import_workspace(zip_path: str) -> Workspace` — descompacta, restaura workspace + domains + items + artifacts + relations com IDs novos
  - `export_domain(workspace_id: str, domain_id: str) -> bytes` — retorna ZIP de domain
  - `import_domain(workspace_id: str, zip_path: str) -> Domain` — descompacta e restaura domain + items + artifacts + relations

Estrutura do ZIP (export):
```
manifest.json         # {version, type, name, exported_at, counts}
workspace.json        # {workspace, domains, items, relations}
artifacts/            # binários (copiar de ARTIFACTS_DIR)
relations.json        # [relações]
```

**S3. src/schemas/artifact_schemas.py**
- `ArtifactCreate` — item_id, file_path
- `ArtifactResponse` — id, item_id, filename, file_size, mime_type, created_at

**S4. src/mcp/artifact_tools.py**
```python
@mcp.tool()
def artifact_attach(item_id: str, file_path: str) -> dict:
    """Anexa arquivo a um item."""
    # Valida, chama ArtifactService.attach()
    # Retorna ArtifactResponse

@mcp.tool()
def artifact_list(item_id: str) -> list[dict]:
    """Lista artifacts de um item."""
    # Retorna list[ArtifactResponse]

@mcp.tool()
def artifact_get(artifact_id: str) -> bytes:
    """Obtém artifact (binário)."""
    # Retorna conteúdo em bytes (possivelmente base64)
```

Função `register(mcp)`.

**S5. Completar workspace_import / domain_import**
- `src/mcp/workspace_tools.py`: `workspace_import` agora chama `ImportExportService.import_workspace(file_path)`
- `src/mcp/domain_tools.py`: `domain_import` agora chama `ImportExportService.import_domain(workspace, file_path)`

**S6. src/main.py — Registrar TODOS os tools**
```python
def register_all_tools() -> None:
    from src.mcp import (
        workspace_tools, domain_tools, item_tools,
        relation_tools, memory_tools, tag_tools, label_tools, artifact_tools
    )
    workspace_tools.register(mcp)
    domain_tools.register(mcp)
    item_tools.register(mcp)
    relation_tools.register(mcp)
    memory_tools.register(mcp)
    tag_tools.register(mcp)
    label_tools.register(mcp)
    artifact_tools.register(mcp)
```

Total de tools: 6 + 6 + 5 + 3 + 2 + 3 + 3 + 3 = 31 tools MCP.

**S7. Tests**
- `tests/test_artifacts.py` — artifact_attach, artifact_list, artifact_get
- `tests/test_import_export.py` — export_workspace, import_workspace, export_domain, import_domain

### Critério de Sucesso
✓ `pytest tests/ -v` — todos os testes passam (deve ter 30+ testes agora)
✓ `python src/main.py --bootstrap` → bootstrap: OK
✓ `python src/main.py --check-db` → database: connected
✓ 31 tools registrados no MCP server
✓ ZIP export/import funcional (manifest.json + estrutura correta)
✓ artifact_attach/get funciona com arquivo real

### Padrões
- Type hints 100%
- Docstrings em todas as functions públicas
- get_session(get_engine()) para DB
- Exceções: NotFoundError, ValidationError, DatabaseError
- Logs com logger
- ZIP criado com ZipFile (stdlib)

### Nota
- T3, T4 completaram: item_tools, relation_tools, memory_tools, tag_tools, label_tools já existem e têm tests
- Não mexer em models.py, session.py, config.py, migrations.py
- Arquivo ou binário em artifact: usar file_path para lê-lo e ARTIFACTS_DIR para armazenar
- Código em feature/mcp-knowledge-os branch
