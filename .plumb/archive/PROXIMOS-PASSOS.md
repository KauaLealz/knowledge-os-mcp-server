# Próximos Passos — v0.1 → v0.1.1 → v0.2

## 🎯 Imediato (Após T6)

### 1. Merge em Main (TODAY)
```bash
# Verificar T6 completado
git log --oneline -1  # deve ser commit de T6

# Merge local
git checkout main
git merge --no-ff feature/mcp-knowledge-os -m "Merge mcp-knowledge-os v0.1"

# Tag v0.1.0
git tag -a v0.1.0 -m "MCP Knowledge OS v0.1.0 — MVP completo"

# Push
git push origin main
git push origin v0.1.0

# Cleanup
git branch -d feature/mcp-knowledge-os
git push origin --delete feature/mcp-knowledge-os
```

### 2. Correção de Erros (1-2 dias)
```bash
# Criar branch v0.1.1
git checkout -b v0.1.1-hotfixes

# Priority 1: WorkspaceService.delete
# - Arquivo: src/services/workspace_service.py
# - Adicionar cascade cleanup antes de delete

# Priority 2: exceptions.py duplicatas
# - Arquivo: src/exceptions.py
# - Consolidar NotFoundError, ValidationError

# Priority 3: datetime.utcnow
# - Arquivo: src/db/models.py
# - Trocar por datetime.now(timezone.utc)

# Testar
pytest tests/ -v
ruff check src/
python src/main.py --bootstrap

# Merge
git checkout main
git merge v0.1.1-hotfixes -m "v0.1.1: correções críticas"
git tag -a v0.1.1 -m "MCP Knowledge OS v0.1.1 — bug fixes"
git push origin main
git push origin v0.1.1
```

### 3. Documentação (1-2 dias)
- [ ] DEPLOYMENT.md — como rodar em produção
- [ ] CONTRIBUTING.md — guia para contribuidores
- [ ] ARCHITECTURE.md revisado (T6 deve ter criado)
- [ ] API.md — referência de todas as 32 tools

---

## 📋 v0.2 Roadmap (2-3 Meses)

### Sprint 2.1: Front Web (3-4 semanas)

**Objetivo:** Interface web para CRUD de workspaces, domains, items

**Tarefas:**
- [ ] Setup Vite + React + TypeScript
- [ ] Component library (shadcn/ui)
- [ ] API client (TanStack Query)
- [ ] Pages: Home, Workspace, Domain, Item, Search
- [ ] Forms: create/update workspace, domain, item
- [ ] Export/Import UI
- [ ] Tests (Vitest + React Testing Library)

**Stack:**
```
web/
├── React 18
├── TypeScript
├── Tailwind CSS
├── TanStack Query (data fetching)
├── Zod (validation)
└── Vitest (testing)
```

**Entrega:** Web app funcional, 100% cobertura CRUD

---

### Sprint 2.2: Multi-Database Support (2-3 semanas)

**Objetivo:** Suportar MySQL, PostgreSQL remoto/local

**Tarefas:**
- [ ] Refatorar src/config.py para URL polimórfica
- [ ] Suporte MySQL+pymysql (com FTS fallback)
- [ ] Suporte PostgreSQL+psycopg (com tsvector)
- [ ] Testes: test_mysql.py, test_postgresql.py
- [ ] Metastore (opcional, para multi-workspace)
- [ ] Migração de dados (SQLite → PostgreSQL)

**Stack:**
```
src/db/
├── session.py (atualizado para suportar N dbs)
├── migrate.py (novo, para migração)
└── dialects/
    ├── sqlite.py
    ├── mysql.py
    └── postgresql.py
```

**Entrega:** DB agnóstico, testes com 3 DBs

---

### Sprint 2.3: Permissionamento (2-3 semanas)

**Objetivo:** RBAC (owner/editor/viewer), multi-user safe

**Tarefas:**
- [ ] Modelos: User, Role, WorkspaceMember, DomainMember
- [ ] AuthService + PermissionService
- [ ] Middleware de autenticação (JWT simples ou OAuth)
- [ ] Decoradores @requires_permission para tools
- [ ] Testes: test_permissions.py
- [ ] Frontend: role badges, disable buttons sem acesso

**Stack:**
```
src/
├── auth.py (novo)
├── models.py (adicionar User, Role)
├── services/permission_service.py (novo)
└── mcp/auth_tools.py (novo)
```

**Entrega:** Controle de acesso funcionando, testes e UI

---

### Sprint 2.4: Workflow + Curadoria (4-5 semanas)

**Objetivo:** Aprovação de items, audit trail, workflow editorial

**Tarefas:**
- [ ] Modelos: Organization, Team, ItemApproval, AuditLog
- [ ] ItemApprovalService (criar, revisar, aprovar/rejeitar)
- [ ] Status workflow (draft → pending_review → approved/rejected)
- [ ] Dashboard: itens aguardando review
- [ ] Audit trail: quem/quando/como
- [ ] Frontend: workflow UI (approve/reject com feedback)
- [ ] Testes: test_approval_workflow.py

**Stack:**
```
src/
├── services/approval_service.py (novo)
├── services/organization_service.py (novo)
├── mcp/approval_tools.py (novo)
└── models.py (novos: Organization, Team, ItemApproval)
```

**Entrega:** Workflow editorial funcionando end-to-end

---

## 📊 Estimates

| Component | Effort | Risk | Notes |
|-----------|--------|------|-------|
| Front Web | 20-25 days | Low | React é padrão, T6 já validou API |
| Multi-DB | 12-15 days | Medium | PostgreSQL é novo, MySQL pode ter issues com FTS |
| Permissions | 12-15 days | Low | RBAC é well-known pattern |
| Workflow | 20-25 days | Medium | Novo modelo de dados, requer teste extensivo |
| **Total v0.2** | **64-80 days** | **Medium** | **~16 semanas ≈ 4 meses** |

---

## 🚦 Go/No-Go Criteria para v0.2

**Go criteria (tudo deve passar):**
- [ ] v0.1.1 released (erros corrigidos)
- [ ] Front web: 100% CRUD coverage
- [ ] PostgreSQL passing tests
- [ ] Permissions: 90%+ test coverage
- [ ] Workflow: end-to-end teste (criar → revisar → aprovar)
- [ ] Zero breaking changes com v0.1

**No-Go criteria (pausa se algum hit):**
- [ ] Multi-DB testing < 70% coverage
- [ ] Performance degradação > 20%
- [ ] Security audit findings críticos

---

## 📞 Communication Plan

**Stakeholders:** Team, users, contributors

- [ ] Release v0.1.0 (announce no README, GitHub Releases)
- [ ] Roadmap v0.2 publicado (ROADMAP.md)
- [ ] Bi-weekly updates (progress, blockers)
- [ ] Community feedback loop (GitHub Discussions)

---

## 🎯 Success Metrics v0.2

- **Usability:** 5+ external users testando
- **Performance:** Item search < 200ms (100 items)
- **Stability:** 99.9% uptime (no bugs críticos em 1 mês)
- **Coverage:** 85%+ test coverage
- **Documentation:** API + Frontend docs completos

---

## 📝 Template para Próximas Tasks

```markdown
# Task T7: Multi-Database Support

## Objective
Suportar MySQL, PostgreSQL, SQLite em paralelo.

## Deliverables
- [ ] URL polimórfica em config.py
- [ ] MySQL+pymysql support
- [ ] PostgreSQL+psycopg support
- [ ] Migration script (SQLite → PostgreSQL)
- [ ] test_mysql.py, test_postgresql.py

## Acceptance Criteria
- [ ] pytest tests/ → 100+ testes, todos passed
- [ ] Suporta 3 DBs (SQLite, MySQL, PostgreSQL)
- [ ] FTS funciona em todas (ou fallback elegante)
- [ ] Migração de dados validada

## Risks
- MySQL FTS é diferente (pode bloqueado)
- PostgreSQL versões diferentes (9.6 vs 14+)
```

---

**Próximo:** Aguardar T6 completar → Merge → Iniciar v0.1.1 hotfixes
