# MCP Knowledge OS — Sumário Executivo

**Versão:** v0.1.0  
**Data:** 2026-10-02  
**Status:** ✅ T1–T6 concluídas (pendente: merge)  
**Branch:** `master` (a branch `feature/mcp-knowledge-os` não existe no repositório)  

---

## 🎯 O que foi entregue

Um **servidor MCP (Model Context Protocol) local e completo** que funciona como a fonte única de conhecimento para agentes Claude, substituindo:
- `.cursor/rules`, `CLAUDE.md`, `AGENTS.md`
- Runbooks, notas, snippets, skills customizadas
- Documentação operacional

**Princípios implementados:**
- ✅ Local-first (nenhuma dependência externa)
- ✅ SQLite criptografado (AES-256 com SQLCipher, opcional)
- ✅ Pouquíssimo RAM (<100MB)
- ✅ Projetado para consumo por agentes
- ✅ Sem embeddings, sem LLM interno
- ✅ Curadoria humana (agente responsável)

---

## 📦 Componentes Entregues

### Core Database
- **8 SQLAlchemy Models:**
  - Workspace (contexto grande)
  - Domain (projeto/assunto)
  - Item (unidade de conhecimento)
  - Tag, Label, Relation (metadados)
  - Artifact (arquivos reutilizáveis)

- **Full-Text Search:** FTS5 em title + summary + content
- **Features:** WAL mode, PRAGMA optimization, criptografia AES-256 (opcional)

### Services Layer (8 Services + ImportExportService)
1. **WorkspaceService** — CRUD + export
2. **DomainService** — CRUD + export
3. **ItemService** — CRUD + FTS5 search (Principal)
4. **RelationService** — relações semânticas
5. **MemoryService** — promoção + renovação TTL
6. **TagService** — tags reutilizáveis
7. **LabelService** — labels controladas
8. **ArtifactService** — arquivos anexados
9. **ImportExportService** — export/import ZIP de workspace e domain

### MCP Tools (32 Total)
```
Workspace (6)        Domain (6)         Item (5)          Relations (3)
├─ create           ├─ create          ├─ create         ├─ create
├─ list             ├─ list            ├─ update         ├─ list
├─ get              ├─ get             ├─ delete         └─ delete
├─ delete           ├─ delete          ├─ get
├─ export           ├─ export          └─ search (FTS5)
└─ import           └─ import

Memory (2)           Tags (3)           Labels (3)        Artifacts (3)
├─ promote          ├─ create          ├─ create         ├─ attach
└─ renew            ├─ list            ├─ list           ├─ list
                    └─ delete          └─ delete         └─ get

+ health_check (1)
```

### Data Models
- **7 Item Types:** context, rule, pattern, procedure, knowledge, insight, artifact
- **4 Memory Classes:** ephemeral (TTL), working, longterm, canonical
- **6 Relation Types:** related_to, depends_on, implements, references, supersedes, derived_from
- **5 Default Labels:** official, critical, experimental, deprecated, reference

---

## 📊 Métricas de Qualidade

| Métrica | Valor |
|---------|-------|
| **Testes** | 104 passed (pytest) |
| **Cobertura** | 88% (src/, medida em e52af23) |
| **Tools MCP** | 32 |
| **Services** | 9 |
| **Models** | 8 |
| **Lint (ruff)** | 21 pendências em models.py, migrations.py, conftest.py, test_db.py (pré-existentes) |
| **Type check (mypy)** | 59 erros em 13 arquivos (maioria `Column[...]` vs tipo escalar do SQLAlchemy); a corrigir |
| **Formato (black)** | 15 arquivos fora do padrão; não reformatados |
| **Commits** | 5 de feature (T1–T5) + T6 |

---

## 🚀 Como Usar

### Setup
```bash
# Instalar
pip install -e ".[dev]"

# Bootstrap (cria banco, labels padrão)
python src/main.py --bootstrap

# Verificar
python src/main.py --check-db

# Iniciar servidor MCP
python src/main.py
```

### Exemplo: Criar Workspace + Domain + Item
```python
# MCP Client chama:

workspace_create({
  "name": "BTG",
  "description": "Workspace principal"
})

domain_create({
  "workspace": "BTG",
  "name": "Orquestra 2.0"
})

item_create({
  "workspace": "BTG",
  "domain": "Orquestra 2.0",
  "type": "knowledge",
  "memory_class": "longterm",
  "title": "ConditionalOnProperty não é dinâmico",
  "summary": "Spring: avalia em startup, não em runtime",
  "content": "Detalhamento...",
  "tags": ["spring", "java"],
  "labels": ["official"],
  "confidence": 95,
  "importance": 8
})

# Buscar
item_search({
  "workspace": "BTG",
  "query": "ConditionalOnProperty",
  "limit": 10
})
# Retorna: [{id, title, summary, score}] — SEM content
```

---

## 📚 Documentação

- **README.md** — Setup, uso, conceitos, ferramentas (completo)
- **docs/FLUXO_COMPLETO.md** — Exemplo end-to-end detalhado
- **docs/ARQUITETURA.md** — Diagrama alto-nível
- **docs/EXEMPLO_SETUP.md** — Passo-a-passo para novo usuário
- **Makefile** — Targets para dev (test, lint, bootstrap, etc)

---

## 🔧 Stack Técnico

| Componente | Tecnologia |
|-----------|------------|
| **MCP Framework** | FastMCP |
| **Runtime** | Python 3.12+ |
| **ORM** | SQLAlchemy 2.x |
| **Validação** | Pydantic v2 |
| **Banco de Dados** | SQLite + FTS5 |
| **Criptografia** | SQLCipher (AES-256, opcional) |
| **Testes** | pytest + fixtures |
| **Lint** | ruff |
| **Type Checking** | mypy |

---

## 🎯 Decisões de Design

### FTS5 vs Database Search
**Escolha:** FTS5 virtual table com triggers automáticos
- **Por quê:** Mais rápido (índice invertido), score BM25 nativo, suporta complexos queries

### Summary vs Content
**Escolha:** `item_search` retorna summary, `item_get` retorna content
- **Por quê:** Economia de banda e latência para agentes

### Memory Classes
**Escolha:** ephemeral (TTL), working, longterm, canonical
- **Por quê:** Controle fino de ciclo de vida (v0.1: manual; v0.2: cron cleanup)

### Relações Semânticas
**Escolha:** Sem cardinalidade forçada, tipos explícitos (6 tipos)
- **Por quê:** Flexibilidade + rastreabilidade

---

## ✅ Checklist de Aceite

- [x] T1: Config + Models + Tests (9 testes)
- [x] T2: Workspace + Domain (12 tools, 17 testes)
- [x] T3: Item + FTS5 (5 tools, 27 testes)
- [x] T4: Relations + Memory + Tags (11 tools, 31 testes)
- [x] T5: Artifacts + Import/Export + Main (32 tools, 104 testes)
- [x] T6: Testes finais + Docs

**Requisitos Atendidos:**
- [x] Local-first
- [x] SQLite + FTS5
- [x] SQLCipher opcional
- [x] 32 ferramentas MCP
- [x] Export/Import ZIP
- [x] Testes (104, cobertura 88%)
- [x] Documentação completa
- [ ] Código limpo: ruff, mypy e black ainda têm pendências (ver Métricas)

---

## 🔮 Roadmap (v0.2+)

- **Memory Cleanup:** Cron job para ephemeral TTL
- **Web UI:** React dashboard (browse, search, create)
- **CLI:** `knowledge-mcp` command-line tool
- **Claude Code Integration:** Plugin para instalação automática
- **Git Sync:** Backup automático de exports
- **Performance:** Caching, query optimization

---

## 📝 Branch & Merge

**Branch:** `master`  
**Status:** Funcional e testado; revisar as pendências de lint/typecheck antes do merge/tag  

```bash
# Tag v0.1.0 (após resolver as pendências)
git tag v0.1.0
git push origin v0.1.0
```

---

## 👨‍💻 Autor

Implementado com Claude Sonnet 5.5 — arquitetura e implementação paralela (T1–T6).

**Modelo:** Claude Sonnet 5.5  
**Commits:** T1 a T6  
**Esforço:** Trilha Profunda, paralelização máxima  

---

## 📞 Suporte

- **Documentação:** Veja `docs/` e `README.md`
- **Issues:** GitHub issues no repositório
- **Desenvolvimento:** Veja `.plumb/changes/mcp-knowledge-os.md` para histórico

---

**Status Final:** v0.1 funcional; qualidade estática (mypy/black) pendente

Data de Conclusão: 2026-10-02  
Próximo Release: v0.2 (Memory cleanup + Web UI)
