# Status — MCP Knowledge OS

**Versão:** v0.1.0 (WIP)  
**Trilha:** Profunda  
**Data:** 2026-10-02  

## Tasks

| # | Tarefa | Status | Progresso |
|---|--------|--------|-----------|
| T1 | Configuração e Modelos | 🔄 In Progress | FTS5 triggers ✓, migrations ?, tests ? |
| T2 | Ferramentas Workspace + Domain | ⏳ Pending | - |
| T3 | Ferramentas Item (Core) | ⏳ Pending | - |
| T4 | Ferramentas Auxiliares | ⏳ Pending | - |
| T5 | Artifacts + Main Server | ⏳ Pending | - |
| T6 | Testes + Documentação | ⏳ Pending | - |

## Arquivos Criados

### Documentação
- ✅ README.md — setup, uso, conceitos, ferramentas
- ✅ docs/FLUXO_COMPLETO.md — exemplo end-to-end completo
- ✅ .env.example — variáveis de configuração
- ✅ Makefile — targets para dev (test, lint, bootstrap, etc)

### Configuração
- ✅ pyproject.toml — dependencies e build config
- ✅ .gitignore — ignora __pycache__, .pytest_cache, database/, etc

### Código Principal
- ✅ src/config.py — load variables, validation
- ✅ src/db/models.py — 8 modelos SQLAlchemy (Workspace, Domain, Item, Tag, Label, Relation, Artifact, ItemTag, ItemLabel)
- ✅ src/db/session.py — engine init, FTS5 table + triggers, WAL mode, PRAGMA
- ✅ src/exceptions.py — ConfigError, DatabaseError
- ✅ src/main.py — FastMCP skeleton

### Services (Stubs)
- ✅ src/services/workspace_service.py — TODO: CRUD + export/import
- ✅ src/services/domain_service.py — TODO: CRUD + export/import
- ✅ src/services/item_service.py — TODO: CRUD + search (FTS5)
- ✅ src/services/relation_service.py — TODO: CRUD relations
- ✅ src/services/memory_service.py — TODO: promote + renew
- ✅ src/services/tag_service.py — TODO: CRUD tags
- ✅ src/services/import_export_service.py — TODO: ZIP export/import

### MCP Tools (Stubs)
- ✅ src/mcp/ — workspace, domain, item, relation, memory, tag, artifact tools

### Plumb
- ✅ .plumb/changes/mcp-knowledge-os.md — especificação completa
- ✅ .plumb/references/change-template.md — template para mudanças

## Próximos Passos

### T1 (Em Progresso)
- [ ] Completar src/db/migrations.py (bootstrap labels padrão)
- [ ] Criar tests/conftest.py (pytest fixtures)
- [ ] Criar tests/test_db.py (6+ testes de modelo)
- [ ] Melhorar src/main.py (--check-db, --bootstrap args)

### T2 (Será Despachado)
- [ ] workspace_service.py completo (CRUD + ZIP export/import)
- [ ] domain_service.py completo (CRUD + ZIP export/import)
- [ ] mcp/workspace_tools.py (6 tools)
- [ ] mcp/domain_tools.py (6 tools)

### T3 (Será Despachado)
- [ ] item_service.py (CRUD + FTS5 search)
- [ ] mcp/item_tools.py (5 tools, search retorna summary)
- [ ] Pydantic schemas para ItemCreate, ItemUpdate, ItemSearch

### T4 (Será Despachado)
- [ ] relation_service.py (CRUD relations)
- [ ] mcp/relation_tools.py (3 tools)
- [ ] memory_service.py (promote, renew)
- [ ] mcp/memory_tools.py (2 tools)
- [ ] tag_service.py (CRUD tags)
- [ ] mcp/tag_tools.py (3 tools)

### T5 (Será Despachado)
- [ ] artifact_service.py (attach, list, get)
- [ ] mcp/artifact_tools.py (3 tools)
- [ ] import_export_service.py (ZIP handling completo)
- [ ] src/main.py (registra TODOS os tools)

### T6 (Será Despachado)
- [ ] Suite de testes completa (pytest, mocks, fixtures)
- [ ] Documentação final (README, docs/)
- [ ] .env.example consolidado
- [ ] Coverage report

## Commits

| Hash | Mensagem |
|------|----------|
| f42861f | mcp-knowledge-os: estrutura inicial (config, models, session, main skeleton) |
| (T1) | T1: Configuração, migrations, testes |
| (T2) | T2: Workspace + Domain tools |
| (T3) | T3: Item tools com FTS5 |
| (T4) | T4: Relations, Memory, Tags |
| (T5) | T5: Artifacts + Main server |
| (T6) | T6: Testes, documentação, finalização |

## Notas

- Branch: `feature/mcp-knowledge-os`
- Base: `main`
- FastMCP em uso (padrão: decoradores @mcp.tool())
- SQLite + FTS5 (sem embeddings)
- SQLCipher opcional (AES-256)
- Memory cleanup (ephemeral TTL) → phase 2 (cron job)

## Commands Rápidos

```bash
# Setup
make install
make dev

# Develop
make bootstrap    # Cria banco + labels padrão
make check-db     # Testa conexão
make test         # Roda testes
make lint         # Lint com ruff
make format       # Formata com black

# Run
make run          # Inicia servidor MCP

# Clean
make clean        # Remove artifacts
```

---

**Última atualização:** 2026-10-02 — T1 em progresso
