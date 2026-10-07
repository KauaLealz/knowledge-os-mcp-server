# Arquitetura

Voltar ao [README](../README.md). Uso das ferramentas: [MCP_USAGE.md](MCP_USAGE.md).

## Camadas

```
Agente (Claude Code, Cursor)          Hook de início de sessão      Navegador
   │ MCP stdio                           │ knowledge-mcp context      │ knowledge-mcp ui
   ▼                                     ▼                            ▼
knowledge_os/main.py  FastMCP         knowledge_os/cli.py (sem fastmcp)   knowledge_os/api  FastAPI + static
 └─ mcp/tools.py  14 ferramentas         context · recent ·          conexões, teste de remote,
    (sempre registradas, sem perfil)     pending · link              sincronização do índice
   │                                     │                            │
   └──────────────────────┬──────────────┴────────────────────────────┘
                          ▼
knowledge_os/services/   ItemService (save, search, similar, publish) · ContextService
                RepoService · GitRepoService (clone/pull/publish/sync) · item_file (serialização)
                secret_service/secret_guard · RelationService · ImportExport
                          ▼
knowledge_os/db/         models (SQLAlchemy 2) · search_query (PT-BR) · schema_sync · rename_v2
                          ▼
            Por connection: repositório git clonado (`<home>/repos/<id>`) +
            índice SQLite + FTS5 derivado dele (`<home>/indexes/<id>.db`)
```

Ferramentas são finas: resolvem nomes e projeto para ids, chamam um service e devolvem JSON
enxuto. As regras de negócio (idempotência, transação do lote, TTL, supersedes, guarda de
segredo, publicação git) ficam nos services, e por isso CLI, MCP e UI se comportam igual.

## O storage é git, o SQLite é cache

Cada `Connection` (`ConnectionConfig` em `config.py`) é um repositório git: com `remote_url`,
um clone de verdade (GitHub ou outro remote); sem `remote_url`, um repositório git só local
(`git init`). O índice SQLite de cada connection é **derivado** desse repositório — existe só
para a busca (FTS5) ser rápida, e é inteiramente reconstruível a partir dos arquivos `.md`: não
guarda nada que não possa ser recalculado.

- Cada item vira um arquivo Markdown com frontmatter YAML em
  `<workspace-slug>/<project-slug>/<key>.md` (sem key: `.../_sem-key/<id>.md`) — serialização em
  `services/item_file.py` (`serialize_item`/`parse_item_file`).
- `services/git_repo_service.py` (`GitRepoService`) é o único lugar (com `gh_cli.py`) que chama
  `git`/`gh`, sempre via lista de argumentos (nunca `shell=True`): `ensure_clone` (clona ou
  `git init` na primeira vez), `pull`, `sync` (compara `ls-remote` com o HEAD local sem baixar
  objetos; só puxa se mudou), `publish` (escreve, comita e — em modo `pr` — abre PR ou Issue),
  `ensure_workflow` (grava `.github/workflows/validate-items.yml` + script de validação:
  sem segredo, sem key duplicada, roda em cada PR) e `ensure_codeowners`.
- `review_mode`, por connection: `direct` comita (e empurra, se há remote) na branch principal
  na mesma chamada de `item_save`/`item_delete`/`relation_delete`; `pr` escreve numa branch nova
  e abre um Pull Request (ou uma Issue, sem permissão de push) — o índice só reflete a mudança
  depois que o PR for mergeado e `repo(action="sync")` (ou o hook de início de sessão) rodar.
- O catálogo (connection reservada `default`) é sempre um repositório git só local, sem UI de
  connection — guarda o que não está em nenhuma connection cadastrada.

Segredos (`type == "secret"`) nunca viram arquivo: `item_file.serialize_item` recusa com
`ValidationError`. O valor cifrado mora em `<clone-da-connection>/.secrets/<item_id>.enc`,
coberto por um `.gitignore` gerenciado (`secret_service.py`) — nunca entra no git nem no índice;
só `has_value` é rastreável.

## Peças que importam

| Peça | Como funciona | Por quê |
|---|---|---|
| `action=` em vez de uma ferramenta por verbo (`knowledge_os/mcp/tools.py`) | `workspace`/`project`/`subject`/`repo`/`artifact`/`backup` agrupam list/create/rename/merge/delete (ou link/list/unlink/sync, attach/get, export/import) numa única ferramenta cada | menos ferramentas registradas, nomes mais claros — a mesma ideia que `vocabulary` já usava para tags/labels |
| `item_save` (`ItemService.save`) | lote atômico; `key` → upsert, `id` → update, sem nenhum → create + `similar`; `id` + `workspace`/`project`/`subject` novos → move o item; relações por id ou key; numa connection com repositório git, também serializa e publica cada item (`GitRepoService.publish`) | o fechamento de uma mudança grava tudo numa chamada, sem duplicar, e já fica versionado |
| Busca (`search_query.py`) | sem acento, sem stopwords, radical PT-BR, prefixo; AND e, se vazio, OR; pesos BM25 título 6, keywords 4, resumo 3, conteúdo 1 | acerto sem embeddings e sem custo de modelo |
| Pacote de contexto (`ContextService`) | project do repositório + `Geral` do workspace + `Global/Geral`; seções por tipo; regras com `scope_paths` só quando os paths casam; corta no orçamento e lista o omitido | o agente começa sabendo o essencial gastando ~1–1,5 mil tokens |
| Ligação de repositório de código (`RepoService`) | chave = remote do git normalizado (ou `path:` + raiz) → workspace/project; `candidate_match` recusa criar workspace/project novo quando o nome parece (mas não é igual a) um já existente — exige `confirm_new=True` ou o nome exato | o mesmo repositório em qualquer pasta ou máquina acha o mesmo conhecimento, sem workspace/project duplicado por erro de grafia |
| Repositório git da connection (`GitRepoService`) | `ensure_clone`/`pull`/`sync`/`publish`, `direct` ou `pr`, `ensure_workflow`/`ensure_codeowners` | o cérebro vira um repositório git de verdade: histórico, revisão por PR quando quiser, auditável fora do servidor |
| Serialização item↔arquivo (`item_file.py`) | `Item` (ORM ou dict) ↔ Markdown com frontmatter YAML; recusa serializar `secret`; campos de telemetria (`access_count`, `last_accessed`, `expires_at`) nunca vão para o arquivo | o arquivo versionado é só o que faz sentido revisar num diff |
| Ciclo de vida | `ephemeral` expira (`expires_at`); classe só sobe; `supersedes` marca o alvo `superseded`; `deprecated` sai da busca | o contexto não acumula lixo nem conselho velho |
| `secret_guard` / `secret_service` | `secret_guard`: padrões de chaves, tokens, JWT, `password=`, URL com senha (placeholders passam) recusam itens comuns; `secret_service`: segredo vira item sem valor, preenchido só pela UI local, cifrado em arquivo fora do git | o cérebro é lido em toda sessão e publicado em git; segredo ali vaza para todo agente e para o histórico do repositório |
| CLI leve (`knowledge_os/cli.py`) | subcomandos do cérebro não importam fastmcp; erro vira aviso; grava a fila offline `<home>/pending.jsonl` (entradas com `repo`) | o hook roda em toda sessão e nunca pode travá-la |
| Manutenção (`knowledge_os/services/maintenance.py`) | backup do SQLite do catálogo (`backup`) e manutenção diária (`run_daily`: backup, remoção de ephemeral vencidos há mais de 7 dias, checkpoint do WAL) | o banco local se cuida sem ação do usuário |
| Retentativa de escrita (`run_with_retry`, `knowledge_os/db/session.py`) | reexecuta a unidade de trabalho inteira enquanto o banco estiver travado (espera crescente até um orçamento; opcionalmente também em conflito de integridade) e, no fim, vira `DatabaseError` legível | vários processos (agentes, CLI, UI) escrevem no mesmo SQLite sem falhar por lock |
| `schema_sync` | adiciona colunas e índices novos no índice SQLite de cada connection e recria o FTS quando a definição muda (aditivo, roda sempre no startup) | atualizar o pacote não exige migração manual do índice |
| `rename_v2` | migração one-shot (`knowledge-mcp --migrate-v2`), separada do `schema_sync`: renomeia as tabelas e colunas de um banco criado antes da renomeação Project/Repo para o schema atual; faz backup do SQLite antes de mexer; nunca roda sozinha | mudança de schema que não é aditiva (rename) não pode acontecer sem o operador pedir |

## Modelo de dados

`Workspace` 1─N `Project` 1─N `Subject` (opcional) 1─N `Item` (N─N `Tag`, `Label`; 1─N
`Artifact`; `Relation` entre itens). `RepoLink` liga a chave do repositório de código (do
usuário) a workspace/project — não confundir com a `Connection`, que é o repositório git onde o
conhecimento é publicado. `Item` tem `item_key` (único por project, nunca por subject), `type`,
`memory_class`, `status`, `scope_paths` (JSON), `keywords`, `source`, `expires_at`,
`importance`, `confidence`, `access_count`. `items_fts` é uma tabela FTS5 de conteúdo externo
mantida por triggers, no índice SQLite de cada connection.

## Estrutura

```
src/
└── knowledge_os/     pacote instalável (src layout)
    ├── cli.py            ponto de entrada `knowledge-mcp`
    ├── main.py           servidor FastMCP, --bootstrap, --check-db, --migrate-v2, ui
    ├── config.py         home, connections.json (ConnectionConfig: remote_url, review_mode)
    ├── mcp/              tools.py (14 ferramentas), INSTRUCTIONS.md
    ├── services/         regras de negócio, inclusive git_repo_service.py, item_file.py,
    │                     secret_service.py, gh_cli.py
    ├── schemas/          Pydantic v2
    ├── db/               models, session, search_query, schema_sync, rename_v2 — índice SQLite
    └── api/              FastAPI da UI (rotas + static do front React)
tests/                unitários, serviços, ferramentas via Client em memória, stdio e CLI
```
