# Arquitetura — MCP Knowledge OS

Visão de alto nível do v0.1. Para um exemplo de uso ponta a ponta, veja
[FLUXO_COMPLETO.md](FLUXO_COMPLETO.md); para instalar, veja
[EXEMPLO_SETUP.md](EXEMPLO_SETUP.md). Voltar ao [README](../README.md).

## Camadas

```
Cliente MCP (Claude, Claude Code, ...)
        │  STDIO
        ▼
┌──────────────────────────────────────────────────────────┐
│ FastMCP Server — 32 tools            (src/main.py)       │
│  ├─ Workspace (6)  create list get delete export import  │
│  ├─ Domain (6)     create list get delete export import  │
│  ├─ Item (5)       create update delete get search(FTS5) │
│  ├─ Relation (3)   create list delete                    │
│  ├─ Memory (2)     promote renew                         │
│  ├─ Tag (3)        create list delete                    │
│  ├─ Label (3)      create list delete                    │
│  ├─ Artifact (3)   attach list get                       │
│  └─ health_check (1)                                     │
└──────────────────────────────────────────────────────────┘
        │  src/mcp/*_tools.py  (validação via src/schemas/, Pydantic v2)
        ▼
┌──────────────────────────────────────────────────────────┐
│ Services — regras de negócio         (src/services/)     │
│  WorkspaceService   DomainService    ItemService (FTS5)  │
│  RelationService    MemoryService    TagService          │
│  LabelService       ArtifactService                      │
│  ImportExportService (ZIP de workspace/domain; usado     │
│                       pelas tools *_export / *_import)   │
└──────────────────────────────────────────────────────────┘
        │  session_scope / get_engine   (src/db/session.py)
        ▼
┌──────────────────────────────────────────────────────────┐
│ Modelos SQLAlchemy 2.x               (src/db/models.py)  │
│  Workspace  Domain  Item  Tag  Label  Relation  Artifact │
│  + tabelas de associação ItemTag e ItemLabel             │
│  + tabela virtual FTS5 (items_fts) com triggers          │
└──────────────────────────────────────────────────────────┘
        │
        ▼
 SQLite + FTS5 (modo WAL; AES-256 opcional via SQLCipher)
```

Cada tool é fina: resolve nomes para ids, chama um service e serializa a resposta.
As regras (TTL de memória `ephemeral`, unicidade, cascatas) ficam nos services.

## Estrutura do código

```
src/
├── main.py          servidor FastMCP, --bootstrap, --check-db
├── config.py        MCP_DB_PATH, MCP_DB_KEY, LOG_LEVEL, diretórios
├── exceptions.py    ConfigError, DatabaseError, ...
├── db/              models, session (engine, WAL, FTS5), migrations (bootstrap)
├── schemas/         modelos Pydantic de entrada e saída
├── services/        um service por entidade + import/export
└── mcp/             registro das tools por área
```

## Decisões principais

| Decisão | Motivo |
|---|---|
| FTS5 com triggers sobre `title`, `summary`, `content` | Busca rápida com ranking BM25, sem embeddings |
| `item_search` devolve só `summary` | Economiza contexto do agente; `item_get` traz o `content` |
| Classes de memória (`ephemeral`, `working`, `longterm`, `canonical`) | Ciclo de vida explícito; limpeza automática fica para a v0.2 |
| Criptografia opcional (SQLCipher, chave em `MCP_DB_KEY`) | Local-first sem obrigar dependência nativa |
| Export/Import em ZIP | Backup e troca de conhecimento entre máquinas |
| Sem LLM interno | A curadoria é do agente; o MCP só persiste |

## Fluxo de uma chamada

```
item_search(workspace="BTG", query="ConditionalOnProperty")
  → item_tools resolve "BTG" para workspace_id
  → ItemService.search consulta items_fts e ordena por
    importance, confidence, access_count, updated_at
  → retorna [{id, title, summary, score}]  (sem content)
```
