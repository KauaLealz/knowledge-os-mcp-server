# Arquitetura

Voltar ao [README](../README.md). Uso das ferramentas: [MCP_USAGE.md](MCP_USAGE.md).

## Camadas

```
Agente (Claude Code, Cursor)          Hook de início de sessão      Navegador
   │ MCP stdio                           │ knowledge-mcp context      │ knowledge-mcp ui
   ▼                                     ▼                            ▼
knowledge_os/main.py  FastMCP         knowledge_os/cli.py (sem fastmcp)   knowledge_os/api  FastAPI + static
 └─ mcp/tools.py  14 ferramentas         context · recent ·          conexões, schema sync,
    (sempre registradas, sem perfil)     pending · link              migração, navegação
   │                                     │                            │
   └──────────────────────┬──────────────┴────────────────────────────┘
                          ▼
knowledge_os/services/   ItemService (save, search, similar) · ContextService · RepoService
                MemoryService · RelationService · secret_guard · ImportExport · Connection
                          ▼
knowledge_os/db/         models (SQLAlchemy 2) · search_query (PT-BR) · schema_sync · rename_v2 · dialects/
                          ▼
                SQLite + FTS5 (WAL) — padrão · Postgres (tsvector) · MySQL (LIKE)
```

Ferramentas são finas: resolvem nomes e projeto para ids, chamam um service e devolvem JSON
enxuto. As regras de negócio (idempotência, transação do lote, TTL, supersedes, guarda de
segredo) ficam nos services, e por isso CLI, MCP e UI se comportam igual.

## Peças que importam

| Peça | Como funciona | Por quê |
|---|---|---|
| `action=` em vez de uma ferramenta por verbo (`knowledge_os/mcp/tools.py`) | `workspace`/`project`/`subject`/`repo`/`artifact`/`backup` agrupam list/create/rename/merge/delete (ou link/list/unlink, attach/get, export/import) numa única ferramenta cada | menos ferramentas registradas, nomes mais claros — a mesma ideia que `vocabulary` já usava para tags/labels |
| `item_save` (`ItemService.save`) | lote atômico; `key` → upsert, `id` → update, sem nenhum → create + `similar`; `id` + `workspace`/`project`/`subject` novos → move o item; relações por id ou key | o fechamento de uma mudança grava tudo numa chamada, sem duplicar |
| Busca (`search_query.py`) | sem acento, sem stopwords, radical PT-BR, prefixo; AND e, se vazio, OR; pesos BM25 título 6, keywords 4, resumo 3, conteúdo 1 | acerto sem embeddings e sem custo de modelo |
| Pacote de contexto (`ContextService`) | project do repositório + `Geral` do workspace + `Global/Geral`; seções por tipo; regras com `scope_paths` só quando os paths casam; corta no orçamento e lista o omitido | o agente começa sabendo o essencial gastando ~1–1,5 mil tokens |
| Ligação de repositório (`RepoService`) | chave = remote do git normalizado (ou `path:` + raiz) → workspace/project; `candidate_match` recusa criar workspace/project novo quando o nome parece (mas não é igual a) um já existente — exige `confirm_new=True` ou o nome exato | o mesmo repositório em qualquer pasta ou máquina acha o mesmo conhecimento, sem workspace/project duplicado por erro de grafia |
| Ciclo de vida | `ephemeral` expira (`expires_at`); classe só sobe; `supersedes` marca o alvo `superseded`; `deprecated` sai da busca | o contexto não acumula lixo nem conselho velho |
| `secret_guard` | padrões de chaves, tokens, JWT, `password=`, URL com senha; placeholders passam | o cérebro é lido em toda sessão; segredo ali vaza para todo agente |
| CLI leve (`knowledge_os/cli.py`) | subcomandos do cérebro não importam fastmcp; erro vira aviso; grava a fila offline `<home>/pending.jsonl` (entradas com `repo`) | o hook roda em toda sessão e nunca pode travá-la |
| Manutenção (`knowledge_os/services/maintenance.py`) | backup do SQLite do catálogo (`backup`) e manutenção diária (`run_daily`: backup, remoção de ephemeral vencidos há mais de 7 dias, checkpoint do WAL) | o banco local se cuida sem ação do usuário |
| Retentativa de escrita (`run_with_retry`, `knowledge_os/db/session.py`) | reexecuta a unidade de trabalho inteira enquanto o banco estiver travado (espera crescente até um orçamento; opcionalmente também em conflito de integridade) e, no fim, vira `DatabaseError` legível | vários processos (agentes, CLI, UI) escrevem no mesmo SQLite sem falhar por lock |
| `schema_sync` | adiciona colunas e índices novos em bancos existentes e recria o FTS quando a definição muda (aditivo, roda sempre no startup) | atualizar o pacote não exige migração manual |
| `rename_v2` | migração one-shot (`knowledge-mcp --migrate-v2`), separada do `schema_sync`: renomeia as tabelas e colunas de um banco criado antes da renomeação Project/Repo para o schema atual; nunca roda sozinha | mudança de schema que não é aditiva (rename) não pode acontecer sem o operador pedir |

## Modelo de dados

`Workspace` 1─N `Project` 1─N `Subject` (opcional) 1─N `Item` (N─N `Tag`, `Label`; 1─N
`Artifact`; `Relation` entre itens). `RepoLink` liga a chave do repositório a workspace/project.
`Item` tem `item_key` (único por project, nunca por subject), `type`, `memory_class`, `status`,
`scope_paths` (JSON), `keywords`, `source`, `expires_at`, `importance`, `confidence`,
`access_count`. `items_fts` é uma tabela FTS5 de conteúdo externo mantida por triggers.

## Estrutura

```
src/
└── knowledge_os/     pacote instalável (src layout)
    ├── cli.py            ponto de entrada `knowledge-mcp`
    ├── main.py           servidor FastMCP, --bootstrap, --check-db, --migrate-v2, ui
    ├── config.py         home, connections.json, validação de conexões
    ├── mcp/              tools.py (14 ferramentas), INSTRUCTIONS.md
    ├── services/         regras de negócio
    ├── schemas/          Pydantic v2
    ├── db/               models, session, dialects, search_query, schema_sync, rename_v2
    └── api/              FastAPI da UI (rotas + static do front React)
tests/                unitários, serviços, ferramentas via Client em memória, stdio e CLI
```
