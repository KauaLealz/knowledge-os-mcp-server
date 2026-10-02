# MCP Knowledge OS

**Status:** Em progresso

**Trilha:** Profunda (novo MCP com banco de dados, segurança, múltiplas ferramentas)

## Decisões — Gate 1 Aprovado ✓

1. **Memory cleanup**: Cron job (não manual)
2. **SQLCipher**: Opcional (sem chave, funciona com SQLite simples)
3. **Export/Import**: Preserva relacionamentos + artifacts como binários

## Objetivo

Criar um MCP local que funcione como a fonte única de conhecimento para agentes Claude, substituindo:
- `.cursor/rules`, `CLAUDE.md`, `AGENTS.md`
- Runbooks, notas pessoais, snippets
- Skills customizadas e documentação operacional

## Princípios

- **Local-first**: Nenhuma dependência de serviços externos
- **SQLite criptografado**: AES-256 com SQLCipher (opcional)
- **Pouquíssimo consumo de RAM**: Adequado para agentes em lotes
- **Projetado para agentes**: Sem embeddings, sem LLM interno, sem classificação automática
- **Curadoria humana**: Agente responsável, MCP apenas persiste e recupera

## Stack

| Componente | Tecnologia |
|---|---|
| Runtime | Python 3.12+ |
| MCP Framework | FastMCP |
| Banco de dados | SQLite + FTS5 |
| Criptografia | SQLCipher (opcional) |
| ORM | SQLAlchemy 2.x |
| Schemas | Pydantic v2 |

## Modelo Conceitual

```
Workspace (grande contexto)
└── Domain (projeto/assunto)
    └── Item (conhecimento)
```

**Exemplo:**
```
BTG
├── Orquestra 2.0
├── OpenSearch
└── Kubernetes

Personal
├── Cursor
├── MCP
└── Homelab
```

## Item Types

| Tipo | Propósito | Exemplo |
|---|---|---|
| `context` | Descreve ambiente | Arquitetura, stack, limitações |
| `rule` | Substitui .cursor/rules, Claude Rules | "Sempre validar entrada no boundary" |
| `pattern` | Padrões recorrentes | Hexagonal Architecture, MCP Pattern |
| `procedure` | Passo a passo | Deploy, rollback, provisioning |
| `knowledge` | Fatos aprendidos | "ConditionalOnProperty não é dinâmico" |
| `insight` | Observações e tradeoffs | "Sonnet é melhor para refactors longos" |
| `artifact` | Arquivos reutilizáveis | JSON, YAML, Docker Compose, Helm |

## Classes de Memória

| Classe | TTL | Propósito |
|---|---|---|
| `ephemeral` | Obrigatório (7, 15, 30 dias) | Curto prazo, expiração automática |
| `working` | Opcional | Em validação |
| `longterm` | Nenhum | Persistente |
| `canonical` | Nenhum | Oficial, promovido explicitamente |

## Critérios de Aceite

### AC1: Modelo de Dados
- [ ] Tabelas: workspaces, domains, items, tags, item_tags, labels, item_labels, relations
- [ ] FTS5 virtual table para busca full-text
- [ ] Chave estrangeira workspace_id → domains, domain_id → items
- [ ] Índices em: workspace_id, domain_id, type, memory_class, created_at, updated_at

### AC2: Ferramentas MCP (19 total)
**Workspace (6):**
- [ ] workspace_create, workspace_list, workspace_get, workspace_delete, workspace_export, workspace_import

**Domain (6):**
- [ ] domain_create, domain_list, domain_get, domain_delete, domain_export, domain_import

**Item (5):**
- [ ] item_create, item_update, item_delete, item_get, item_search (principal)

**Relations (3):**
- [ ] relation_create, relation_list, relation_delete

**Memory (2):**
- [ ] memory_promote, memory_renew

**Artifacts (3):**
- [ ] artifact_attach, artifact_list, artifact_get

**Tags (3):**
- [ ] tag_create, tag_list, tag_delete

### AC3: Otimizações para Agentes
- [ ] item_search sempre retorna `summary` (nunca `content` por padrão)
- [ ] item_get retorna conteúdo completo
- [ ] Ordenação padrão: importance desc, confidence desc, access_count desc, updated_at desc
- [ ] Filtros aceitos: workspace, domain, type, memory_class, tags, labels

### AC4: Segurança
- [ ] MCP_DB_PATH e MCP_DB_KEY via variáveis de ambiente
- [ ] Suporte a SQLCipher com PRAGMA key
- [ ] Validação de entrada via Pydantic schemas

### AC5: Export/Import
- [ ] workspace.zip contém: manifest.json, workspace.json, domains/, items/, artifacts/, relations/
- [ ] Import restaura estrutura completa

## Fora de Escopo

- Cron para memory_cleanup (será implementado em phase 2)
- Interface web ou CLI (apenas MCP tools)
- Sincronização com Cloud (local-first only)
- Embeddings ou busca semântica
- Recomendações automáticas

## Tasks

### T1: Configuração e Modelos
- [ ] `pyproject.toml` com dependencies (FastMCP, SQLAlchemy, Pydantic, SQLCipher)
- [ ] `src/config.py`: carrega MCP_DB_PATH e MCP_DB_KEY
- [ ] `src/db/models.py`: define todos os modelos SQLAlchemy
- [ ] `src/db/session.py`: SessionLocal e get_session()
- [ ] Migração inicial com Alembic ou script de bootstrap
- **Comando de verificação:** `python src/main.py --check-db && python -m pytest tests/test_db.py -v`

### T2: Ferramentas Workspace + Domain
- [ ] `src/services/workspace_service.py`: CRUD + export/import
- [ ] `src/services/domain_service.py`: CRUD + export/import
- [ ] `src/mcp/workspace_tools.py`: registra as 6 tools
- [ ] `src/mcp/domain_tools.py`: registra as 6 tools
- **Comando de verificação:** `pytest tests/test_workspace_tools.py tests/test_domain_tools.py -v`

### T3: Ferramentas Item (Core)
- [ ] `src/services/item_service.py`: create, update, delete, get, search (com FTS5)
- [ ] `src/mcp/item_tools.py`: registra 5 tools
- [ ] Schema Pydantic para ItemCreate, ItemUpdate, ItemSearch
- [ ] Search retorna [{ id, title, summary, score }] sem content
- **Comando de verificação:** `pytest tests/test_item_tools.py -v && python -m pytest tests/test_fts.py -v`

### T4: Ferramentas Auxiliares
- [ ] `src/services/relation_service.py`: CRUD para relations
- [ ] `src/mcp/relation_tools.py`: 3 tools (create, list, delete)
- [ ] `src/services/memory_service.py`: promote, renew
- [ ] `src/mcp/memory_tools.py`: 2 tools
- [ ] `src/mcp/tag_tools.py`: 3 tools (create, list, delete)
- **Comando de verificação:** `pytest tests/test_relations.py tests/test_memory.py tests/test_tags.py -v`

### T5: Artifacts e Main
- [ ] `src/services/import_export_service.py`: ZIP handling
- [ ] `src/mcp/artifact_tools.py`: 3 tools (attach, list, get)
- [ ] `src/main.py`: FastMCP server, registra todos os tools
- [ ] `src/schemas/`: validators para cada ferramenta
- **Comando de verificação:** `python src/main.py --help && pytest tests/test_artifacts.py tests/test_main.py -v`

### T6: Testes e Documentação
- [ ] Suite completa: fixtures pytest, mocks de banco
- [ ] README.md: setup, usage examples, architecture
- [ ] `.env.example`: MCP_DB_PATH, MCP_DB_KEY
- [ ] Exemplo de fluxo completo em docs/
- **Comando de verificação:** `pytest -v --cov=src && python -m pytest tests/ -v`

## Decisões de Design

### FTS5 vs. Database Search
Full-text search via FTS5 trigger, indexado em title + summary + content. Responde a queries com relevância por proximidade de termos.

### Ephemeral TTL
Dados com TTL curto são marcados com `memory_class='ephemeral'` e deletados por cron (fase 2). Sem cleanup automático nesta fase, a responsabilidade é do agente/usuário.

### Summary vs. Content
- **summary**: sempre retornado em buscas (leve)
- **content**: apenas em item_get (pesado)

Economiza largura de banda e tempo de processamento para agentes.

### Relações
Sem cardinalidade forçada — relações são puramente semânticas (related_to, depends_on, implements, references, supersedes, derived_from).

## Riscos

| Risco | Mitigação |
|---|---|
| Crescimento do DB | SQLite + FTS5 suporta milhões de registros. Índices bem colocados. |
| Contenção de escrita | SQLite tem lock global; um agente por vez. Aceitável para local-first. |
| Perda de dados sem backup | Instruir usuário a fazer backups do `database/knowledge.db`. |
| Chave de criptografia exposta | Usar `getpass` ou `.env` com permissões restritas (fase 2: integração com credential managers). |

## Notas

- Não há UI; apenas ferramentas MCP. UIs futuras (web, CLI) consomem as mesmas tools.
- O primeiro workspace/domain/item são criados manualmente via MCP ou script de bootstrap.
- Ordenação padrão favorece importância e confiança — a semântica é: "show me the best stuff first".

## Retro

(Preenchido ao final)

---

**Branch:** `feature/mcp-knowledge-os` (criada após aprovação Gate 1)
**Base:** main
