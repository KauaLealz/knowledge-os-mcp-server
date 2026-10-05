# Arquitetura

Voltar ao [README](../README.md). Uso das ferramentas: [MCP_USAGE.md](MCP_USAGE.md).

## Camadas

```
Agente (Claude Code, Cursor)          Hook de início de sessão      Navegador
   │ MCP stdio                           │ knowledge-mcp context      │ knowledge-mcp ui
   ▼                                     ▼                            ▼
knowledge_os/main.py  FastMCP         knowledge_os/cli.py (sem fastmcp)   knowledge_os/api  FastAPI + static
 ├─ agent_tools.py  6 ferramentas        context · recent ·          conexões, schema sync,
 └─ admin_tools.py  +9 (perfil all)      pending · link              migração, navegação
   │                                     │                            │
   └──────────────────────┬──────────────┴────────────────────────────┘
                          ▼
knowledge_os/services/   ItemService (save, search, similar) · ContextService · ProjectService
                MemoryService · RelationService · secret_guard · ImportExport · Connection
                          ▼
knowledge_os/db/         models (SQLAlchemy 2) · search_query (PT-BR) · schema_sync · dialects/
                          ▼
                SQLite + FTS5 (WAL) — padrão · Postgres (tsvector) · MySQL (LIKE)
```

Ferramentas são finas: resolvem nomes e projeto para ids, chamam um service e devolvem JSON
enxuto. As regras de negócio (idempotência, transação do lote, TTL, supersedes, guarda de
segredo) ficam nos services, e por isso CLI, MCP e UI se comportam igual.

## Peças que importam

| Peça | Como funciona | Por quê |
|---|---|---|
| Perfis de ferramentas (`knowledge_os/mcp/toolset.py`) | `KNOWLEDGE_OS_TOOLSET=agent` registra 6 ferramentas e instruções curtas; `all` registra 15 | definições de ferramenta custam contexto em toda sessão |
| `item_save` (`ItemService.save`) | lote atômico; `key` → upsert, `id` → update, sem nenhum → create + `similar`; relações por id ou key | o fechamento de uma mudança grava tudo numa chamada, sem duplicar |
| Busca (`search_query.py`) | sem acento, sem stopwords, radical PT-BR, prefixo; AND e, se vazio, OR; pesos BM25 título 6, keywords 4, resumo 3, conteúdo 1 | acerto sem embeddings e sem custo de modelo |
| Pacote de contexto (`ContextService`) | domain do projeto + `Geral` do workspace + `Global/Geral`; seções por tipo; regras com `scope_paths` só quando os paths casam; corta no orçamento e lista o omitido | o agente começa sabendo o essencial gastando ~1–1,5 mil tokens |
| Ligação de projeto (`ProjectService`) | chave = remote do git normalizado (ou `path:` + raiz) → workspace/domain | o mesmo repositório em qualquer pasta ou máquina acha o mesmo conhecimento |
| Ciclo de vida | `ephemeral` expira (`expires_at`); classe só sobe; `supersedes` marca o alvo `superseded`; `deprecated` sai da busca | o contexto não acumula lixo nem conselho velho |
| `secret_guard` | padrões de chaves, tokens, JWT, `password=`, URL com senha; placeholders passam | o cérebro é lido em toda sessão; segredo ali vaza para todo agente |
| CLI leve (`knowledge_os/cli.py`) | subcomandos do cérebro não importam fastmcp; erro vira aviso; grava a fila offline `<home>/pending.jsonl` (entradas com `project`) | o hook roda em toda sessão e nunca pode travá-la |
| Manutenção (`knowledge_os/services/maintenance.py`) | backup do SQLite do catálogo (`backup`) e manutenção diária (`run_daily`: backup, remoção de ephemeral vencidos há mais de 7 dias, checkpoint do WAL) | o banco local se cuida sem ação do usuário |
| Retentativa de escrita (`run_with_retry`, `knowledge_os/db/session.py`) | reexecuta a unidade de trabalho inteira enquanto o banco estiver travado (espera crescente até um orçamento; opcionalmente também em conflito de integridade) e, no fim, vira `DatabaseError` legível | vários processos (agentes, CLI, UI) escrevem no mesmo SQLite sem falhar por lock |
| `schema_sync` | adiciona colunas e índices novos em bancos existentes e recria o FTS quando a definição muda | atualizar o pacote não exige migração manual |

## Modelo de dados

`Workspace` 1─N `Domain` 1─N `Item` (N─N `Tag`, `Label`; 1─N `Artifact`; `Relation` entre
itens). `ProjectLink` liga a chave do projeto a workspace/domain. `Item` tem `item_key`
(único por domain), `type`, `memory_class`, `status`, `scope_paths` (JSON), `keywords`,
`source`, `expires_at`, `importance`, `confidence`, `access_count`. `items_fts` é uma tabela
FTS5 de conteúdo externo mantida por triggers.

## Estrutura

```
src/
└── knowledge_os/     pacote instalável (src layout)
    ├── cli.py            ponto de entrada `knowledge-mcp`
    ├── main.py           servidor FastMCP, --bootstrap, --check-db, ui
    ├── config.py         home, connections.json, validação de conexões
    ├── mcp/              toolset, agent_tools, admin_tools, INSTRUCTIONS*.md
    ├── services/         regras de negócio
    ├── schemas/          Pydantic v2
    ├── db/               models, session, dialects, search_query, schema_sync
    └── api/              FastAPI da UI (rotas + static do front React)
tests/                unitários, serviços, ferramentas via Client em memória, stdio e CLI
```
