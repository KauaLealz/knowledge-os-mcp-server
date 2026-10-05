# T9 Spec: 6 Connection Tools Simples

## Objetivo

Adicionar **6 tools práticos** aos 6 de CRUD (T7), totalizando **12 tools de connection** e **44 tools MCP**.

## Tools (Simples, Diretos)

### 1. `connection_init_db(connection_id: str)`
**O que faz:** Cria schema em um banco novo ou existente.

**Use case:** Ao criar uma nova connection, inicializar as tabelas sem criar um workspace vazio.

**Retorna:**
```json
{
  "connection_id": "conn_123",
  "status": "initialized",
  "tables_created": 8,
  "message": "Schema created successfully"
}
```

**Implementação:**
- Chama `init_db(engine)` na connection
- Cria `connections`, `workspaces`, `domains`, `items`, etc
- Trata `table already exists` como OK (idempotente)

---

### 2. `connection_test_detailed(connection_id: str)`
**O que faz:** Testa conexão e retorna info (versão, FTS support, tamanho, latência).

**Use case:** Diagnosticar saúde de uma connection antes de usar.

**Retorna:**
```json
{
  "connection_id": "conn_123",
  "db_type": "postgresql",
  "status": "connected",
  "version": "PostgreSQL 14.5",
  "fts_supported": true,
  "fts_type": "tsvector",
  "tables_count": 8,
  "workspaces_count": 3,
  "items_count": 42,
  "size_mb": 15.3,
  "latency_ms": 5,
  "last_tested": "2026-10-02T14:30:00Z"
}
```

**Implementação:**
- `SELECT VERSION()` → versão
- Verifica dialeto → FTS type
- COUNT em cada tabela
- `SELECT pg_database_size()` ou `PRAGMA page_count`
- Mede tempo de query simples

---

### 3. `migration_preview(from_connection_id: str, to_connection_id: str)`
**O que faz:** Preview da migração sem executar.

**Use case:** "Se eu migrar de SQLite pro PostgreSQL, o que vai acontecer?"

**Retorna:**
```json
{
  "from": "conn_local_sqlite",
  "to": "conn_postgres_prod",
  "workspaces_to_migrate": 3,
  "items_to_migrate": 127,
  "artifacts_count": 8,
  "estimated_time_seconds": 45,
  "size_estimate_mb": 12.5,
  "notes": [
    "Will preserve all tags and labels",
    "FTS indexes will be recreated",
    "No data will be deleted from source"
  ],
  "ready_to_execute": true
}
```

**Implementação:**
- Lê contagens do banco origem
- Checa schema do banco destino (vazio?)
- Estima tempo por operação
- Lista tudo que vai acontecer

---

### 4. `migration_execute(from_connection_id: str, to_connection_id: str, validate: bool = True)`
**O que faz:** Executa migração com validação e rollback automático.

**Use case:** Migrar de SQLite pra PostgreSQL com segurança.

**Retorna:**
```json
{
  "from": "conn_local_sqlite",
  "to": "conn_postgres_prod",
  "status": "success",
  "workspaces_migrated": 3,
  "items_migrated": 127,
  "artifacts_copied": 8,
  "tags_merged": 12,
  "duration_seconds": 42,
  "message": "Migration completed successfully. Source database untouched."
}
```

**Implementação:**
- Chama `MigrationService.migrate()`
- Faz transação no destino
- Valida contagens pós-migração
- Rollback automático se divergir
- Nunca toca na origem (safe)

---

### 5. `workspace_move(workspace_id: str, from_connection_id: str, to_connection_id: str)`
**O que faz:** Move um workspace de uma connection pra outra.

**Use case:** "Quero mover o workspace 'Personal' do SQLite pra PostgreSQL".

**Retorna:**
```json
{
  "workspace_id": "ws_personal",
  "workspace_name": "Personal",
  "from_connection": "conn_local_sqlite",
  "to_connection": "conn_postgres_prod",
  "status": "moved",
  "items_moved": 42,
  "artifacts_moved": 3,
  "duration_seconds": 8,
  "message": "Workspace successfully moved. Source workspace deleted."
}
```

**Implementação:**
- Valida workspace existe na origem
- Cria novo workspace na origem
- Copia domains, items, relations, artifacts
- Deleta workspace antigo (cleanup)
- Atualiza connection_id

---

### 6. `connection_vacuum(connection_id: str)`
**O que faz:** Otimiza banco (índices, ANALYZE, cleanup).

**Use case:** Depois de muitos deletes, melhorar performance.

**Retorna:**
```json
{
  "connection_id": "conn_123",
  "db_type": "postgresql",
  "status": "vacuumed",
  "size_before_mb": 25.3,
  "size_after_mb": 18.5,
  "freed_mb": 6.8,
  "duration_seconds": 12,
  "message": "Database optimized"
}
```

**Implementação:**
- SQLite: `VACUUM` + `ANALYZE`
- PostgreSQL: `VACUUM FULL` + `ANALYZE`
- MySQL: `OPTIMIZE TABLE` para cada tabela
- Mede tamanho antes/depois
- Trata lock com timeout

---

## Resumo

| Tool | Linhas | Complexidade |
|------|--------|-------------|
| connection_init_db | ~20 | Baixa |
| connection_test_detailed | ~30 | Baixa |
| migration_preview | ~25 | Média |
| migration_execute | ~15 | Média |
| workspace_move | ~20 | Média |
| connection_vacuum | ~20 | Baixa |

**Total novo:** ~130 linhas em `src/mcp/connection_tools.py`

**Métodos necessários em services:**
- `ConnectionService.init_db(connection_id)`
- `ConnectionService.test_detailed(connection_id)`
- `MigrationService.preview(from_id, to_id)`
- `MigrationService.execute(from_id, to_id, validate=True)`
- `WorkspaceService.move(workspace_id, from_conn_id, to_conn_id)`
- `ConnectionManager.vacuum(connection_id)`

**Testes:** ~40 (preview, execute, move, vacuum)

**Timeline:** 4-6 horas

---

## Status

- **Após T9:** 44 MCP tools totais (32 T1-T5 + 6 connection CRUD + 6 connection utilities)
- **Integração:** Sem breaking changes (T7-T9 são extensões)
- **Release:** v0.1.0 com 44 tools, 49 commits, docs + API + multi-db

---

**Próximo:** Gate → T9 → Integração T7+T8a+T9 → v0.1.0
