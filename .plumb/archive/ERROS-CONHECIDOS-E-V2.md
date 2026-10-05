# Erros Conhecidos + Roadmap v2

## 🐛 Erros Conhecidos (T1–T5)

### Críticos (Devem ser corrigidos em v0.1.1)

1. **WorkspaceService.delete não remove orphans**
   - Arquivo: `src/services/workspace_service.py`
   - Problema: Ao deletar workspace, relations e artifacts dos items não são removidos
   - Causa: Falta cleanup cascade
   - Impacto: Dados orphans no banco (relações/artifacts órfãs)
   - Solução: Adicionar cascade delete ou explicit cleanup antes de delete

2. **exceptions.py tem duplicatas**
   - Arquivo: `src/exceptions.py`
   - Problema: NotFoundError e ValidationError aparecem 2x
   - Causa: T2 adicionou, T4 revisou e removeu duplicatas, mas verificar se ficou limpo
   - Solução: Verificar e manter apenas 1 definição por exception

3. **models.py com DeprecationWarning**
   - Arquivo: `src/db/models.py`
   - Problema: `datetime.utcnow()` deprecado (usar `datetime.now(timezone.utc)`)
   - Arquivo: `src/db/models.py` — linha com `default=datetime.utcnow`
   - Impacto: Warning em logs
   - Solução: Trocar por `datetime.now(timezone.utc)`

### Não-Críticos (Podem esperar para v0.2)

4. **src/mcp sombreia pacote mcp global**
   - Arquivo: Estrutura de diretórios
   - Problema: `src/mcp/` tem mesmo nome que pacote `mcp` do FastMCP
   - Causa: Ao rodar `python src/main.py`, imports falham porque python acha `src/mcp` antes de `mcp`
   - Impacto: Não consegue importar FastMCP se executado como `python src/main.py`
   - Solução: Renomear `src/mcp/` para `src/tools/` (ou `src/endpoints/`)

5. **artifact_export não retorna ZIP em disco**
   - Arquivo: `src/mcp/artifact_tools.py`
   - Problema: workspace_export e domain_export retornam JSON, não ZIP
   - Causa: Tools implementadas para retornar dados, não arquivos
   - Impacto: Agente pode buscar dados, mas não consegue salvar ZIP
   - Solução: Adicionar workspace_export_file e domain_export_file que salvam em EXPORTS_DIR

6. **FTS5 search sem suporte a operadores complexos**
   - Arquivo: `src/services/item_service.py:search()`
   - Problema: Query vazia com filtros funciona, mas sintaxe FTS5 inválida levanta ValidationError
   - Causa: Sem documentação de sintaxe suportada
   - Solução: Documentar sintaxe FTS5 ou adicionar query builder simples

7. **artifact_get retorna base64 (não binário)**
   - Arquivo: `src/mcp/artifact_tools.py:artifact_get()`
   - Problema: MCP tools não conseguem retornar binários, então usa base64
   - Causa: Limitação do FastMCP
   - Impacto: Cliente precisa decodificar
   - Solução: Adicionar artifact_download que salva em disco

### Antes de Merge (T6 vai verificar)

8. **20 erros de lint em arquivos pré-existentes**
   - Arquivos: models.py, migrations.py, conftest.py, test_db.py
   - Causa: Reescrita do ruff --fix durante T4
   - Solução: Reverter ou corrigir (T6 deve verificar)

---

## ✅ Plano de Correção (v0.1.1)

### Priority 1: Crítico
```
[ ] WorkspaceService.delete — adicionar cascade cleanup
    - Deletar relations dos items do workspace
    - Deletar artifacts dos items do workspace
    - Depois deletar items
    - Depois deletar domains
    - Depois deletar workspace

[ ] Consolidar exceptions.py
    - Verificar se há duplicatas
    - Manter 1 definição por exception
    - Testar imports

[ ] Corrigir datetime.utcnow()
    - Trocar por datetime.now(timezone.utc)
    - Adicionar `from datetime import timezone`
```

### Priority 2: Estrutura
```
[ ] Renomear src/mcp/ para src/tools/
    - Atualizar imports em main.py
    - Atualizar imports em tests/
    - Testar `python src/main.py`
```

### Priority 3: Features
```
[ ] Adicionar workspace_export_file, domain_export_file
    - Salvam ZIP em EXPORTS_DIR
    - Retornam filepath/bytes

[ ] Documentar FTS5 query syntax
    - Adicionar docs/FTS5_QUERY_SYNTAX.md
    - Ejemplos de queries simples

[ ] Adicionar artifact_download
    - Salva arquivo em disco
    - Retorna status + filepath
```

---

## 🚀 Roadmap v2 — Análise Detalhada

### Feature 1: Front Web (UI)

**Requisito do usuário:**
> Front para acessar workspaces, domínios e itens

**Implementação proposta:**

```
tech-stack:
  - React 18+ (ou Vue 3)
  - TypeScript
  - Tailwind CSS
  - Componentes: shadcn/ui ou Material-UI
  - Estado: TanStack Query (data fetching) + Zustand (state)
  - Build: Vite

estrutura:
  web/
  ├── src/
  │   ├── components/
  │   │   ├── Workspace/ (CRUD, list)
  │   │   ├── Domain/ (CRUD, list)
  │   │   ├── Item/ (CRUD, search, detail)
  │   │   ├── Layout/ (sidebar, topbar)
  │   │   └── Forms/ (validation com Zod)
  │   ├── hooks/ (useWorkspaces, useDomains, useItems)
  │   ├── lib/ (API client, utils)
  │   ├── pages/ (router)
  │   └── App.tsx
  ├── package.json
  └── vite.config.ts

API client:
  - OpenAPI spec gerado do FastMCP
  - SDK auto-gerado (openapi-generator)
  - Tipagem 100%

fluxos:
  1. Home: lista workspaces, botão + novo
  2. Workspace: lista domains, botão + novo
  3. Domain: lista items (tabela/cards), botão + novo
  4. Item detail: mostra tudo, edita, deleta
  5. Search: campo global (workspace-wide FTS5)
  6. Export: botão export workspace/domain
  7. Import: botão import ZIP

custo estimado: 3-4 sprints
```

**Integração MCP:**
- FastMCP expõe instrospection → auto-descoberta de tools
- Web chama tools via HTTP bridge (FastMCP já suporta HTTP)
- WebSocket para real-time (opcional v2.1)

---

### Feature 2: Múltiplas Bases de Dados

**Requisito do usuário:**
> Permitir acesso de múltiplas bases

**Implementação proposta:**

```
Opção A: Multi-database mode (recomendado)
  - Cada workspace em banco separado
  - Metastore central (PostgreSQL cloud) com lista de bases
  - Suporta SQLite (local), MySQL (remoto), PostgreSQL (remoto)

Opção B: Metabase mode
  - Um único banco SQLite/MySQL/Postgres com múltiplos schemas
  - Cada workspace em schema próprio

arquitetura (Opção A):
  config.py:
    - METASTORE_URL (central, para listar bases)
    - WORKSPACE_DATABASES = {
        "workspace-1": "sqlite:///...db1.db",
        "workspace-2": "mysql://user:pass@host/db2",
        "workspace-3": "postgresql://user:pass@host/db3"
      }
  
  models/base.py:
    - Classe WorkspaceRegistry (metastore)
    - Métodos: list_workspaces(), get_connection(workspace_id)

  main.py:
    - Middleware que resolve workspace_id do request
    - Carrega engine correto

suporte a dbs:
  sqlite (local):
    - Sem mudanças (já suportado)
    - Adicionar: url validation, path expansion
  
  mysql (remoto):
    - Adicionar driver: `mysql+pymysql://user:pass@host/db`
    - Testar: conexão, criação de tabelas, FTS
    - NOTA: MySQL FTS é diferente (não há FTS5 nativo)
    - Alternativa: usar PostgreSQL em vez de MySQL
  
  postgres (remoto):
    - Adicionar driver: `postgresql+psycopg://user:pass@host/db`
    - FTS: usar pg_trgm ou built-in tsvector
    - Performance: melhor que MySQL para volumes grandes

custo estimado: 2-3 sprints
```

**Impacto em TDD:**
- Nova task: T7 (Multi-database support)
- Refatorar T1 (config) para suportar URL polimórfica
- Novos testes: test_mysql.py, test_postgresql.py

---

### Feature 3: Permissionamento (Read/Write)

**Requisito do usuário:**
> Controle de read/write

**Implementação proposta:**

```
modelo de permissões (RBAC):
  roles:
    - owner: full access (CRUD + export/import)
    - editor: CRUD (create, read, update, delete)
    - viewer: read-only
    - annotator: read + create_item (sem delete)

scope:
  - workspace-level (default)
  - domain-level (mais granular)
  - item-level (muito granular)

implementação:
  tables:
    - workspace_members (workspace_id, user_id, role, scope)
    - domain_members (domain_id, user_id, role, scope)
  
  middleware:
    - RequestContext(user_id, workspace_id)
    - @requires_permission(role="editor", scope="workspace")
    - Verifica permissão antes de executar

  exemplo:
    @mcp.tool()
    @requires_permission(role="editor")
    def item_create(...) -> Item:
        # Só editor+ consegue criar
        ...

custo estimado: 2-3 sprints
```

**Impacto:**
- Nova task: T8 (Permissions + Auth)
- Novo serviço: AuthService, PermissionService
- Novo modelo: User, Role, Permission
- Nova camada: Permission middleware em main.py

---

### Feature 4: Workflow + Curadoria de Equipe

**Requisito do usuário:**
> Workflow com permissionamento e compartilhamento eficiente para trabalhar entre times e separar conhecimento pessoal vs de equipes

**Implementação proposta:**

```
modelo organizacional:
  Organization
    └── Team
        ├── Workspace (compartilhado)
        │   └── Domain (projeto)
        │       └── Item (conhecimento)
        ├── Personal Workspace (privado)
        └── Members (com roles)

permissões:
  - Membro de equipe: acesso só aos workspaces da equipe
  - Membro pode ter role diferentes por workspace
  - Personal workspace: só owner

workflow de curadoria:
  1. Dev cria item em workspace pessoal (draft)
  2. Move para team workspace com status "pending_review"
  3. Lead revisa, aprova ou pede ajustes
  4. Item promovido para "canonical" ou rejeitado
  5. Audit trail: quem aproveu, quando, feedback

implementação:
  tabelas:
    - Organization (name, created_at)
    - Team (org_id, name, description)
    - User (id, name, email)
    - TeamMember (team_id, user_id, role, added_at)
    - WorkspaceMember (workspace_id, user_id, role, added_at)
    - ItemApproval (item_id, approver_id, status, feedback, approved_at)

  campos em Item:
    - owner_id (quem criou)
    - status (draft, pending_review, approved, rejected)
    - approved_by (user_id de quem aprovou)
    - approval_date (quando)
    - approval_feedback (comentário)

  views:
    - WorkspaceDashboard: items pending review
    - PersonalWorkspace: só meus drafts
    - TeamWorkspace: itens da equipe (canonical + approved)

custo estimado: 4-5 sprints
```

---

## 📊 Roadmap Consolidado v2

| Feature | Sprint | Custo | Prioridade | Bloqueia |
|---------|--------|-------|-----------|----------|
| Front Web | 2.1 | 3-4w | Alta | - |
| Multi-DB (Postgres) | 2.2 | 2-3w | Alta | Front |
| Permissionamento | 2.3 | 2-3w | Alta | Front, Multi-DB |
| Workflow + Curadoria | 2.4 | 4-5w | Média | Permissionamento |
| MySQL support | 2.5 | 1-2w | Baixa | Multi-DB |
| WebSocket real-time | 2.6 | 2-3w | Baixa | Front |
| Mobile App | 3.0 | 6-8w | Baixa | Front |

**Total v2:** ~16-22 semanas (4-5 meses de desenvolvimento)

---

## 🎯 Recomendações

### Imediato (após v0.1)
1. **Corrigir erros T1-T5** (1-2 dias)
2. **Renomear src/mcp → src/tools** (1 dia)
3. **Adicionar testes para erros conhecidos** (1 dia)

### v0.1.1
- Correções de bugs
- Melhor documentação de erros
- Performance baseline

### v0.2 MVP (2-3 meses)
- Front básico (CRUD workspaces, domains, items)
- PostgreSQL support
- Permissionamento simples (owner/editor/viewer)

### v0.3+ (roadmap futuro)
- Workflow de curadoria
- Multi-tenant (organizações)
- WebSocket real-time
- Mobile

---

## 📝 Próximos Passos

1. **Finalizar T6** (testes + docs)
2. **Merge em main** (v0.1 oficial)
3. **Tag v0.1.0** e release
4. **Criar branch v0.2** e iniciar tasks
5. **Planejar T7** (Multi-database) com user stories

---

**Autor:** Claude Sonnet 5.5  
**Data:** 2026-10-02  
**Status:** Análise Completa — Pronto para Implementação v2
