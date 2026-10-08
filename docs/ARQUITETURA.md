# Arquitetura

Voltar ao [README](../README.md). Uso das ferramentas: [MCP_USAGE.md](MCP_USAGE.md).

## Camadas

```
Agente (Claude Code, Cursor)          Hook de início de sessão      Navegador
   │ MCP stdio                           │ knowledge-mcp context      │ knowledge-mcp ui
   ▼                                     ▼                            ▼
knowledge_os/main.py  FastMCP         knowledge_os/cli.py (sem fastmcp)   knowledge_os/api  FastAPI + static
 └─ mcp/tools.py  ferramentas            context · recent ·          itens, conexões (listar,
    (sempre registradas, sem perfil)     pending · link · run        editar, testar, padrão, apagar)
   │                                     │                            │
   └──────────────────────┬──────────────┴────────────────────────────┘
                          ▼
knowledge_os/services/   Brain (Snapshot/Draft/commit) · ItemService · ContextService
                RepoService · ConnectionService · GitRepoService (clone/pull/publish/sync)
                item_file (serialização) · secret_service/secret_guard · RelationService
                          ▼
knowledge_os/storage/    access (qual conexão, travas) · files (FileStore) · search (busca em
                         memória) · local_state (repos.json, usage/)
                          ▼
            Por conexão: uma pasta local que é um repositório git (a única fonte de verdade)
```

Ferramentas são finas: resolvem nomes e projeto para ids, chamam um service e devolvem JSON
enxuto. As regras de negócio (idempotência, lote numa publicação só, TTL, supersedes, guarda de
segredo, publicação git) ficam nos services, e por isso CLI, MCP e UI se comportam igual.

## O armazenamento são os arquivos da conexão

Cada conexão (`ConnectionConfig` em `config.py`, cadastrada em `<home>/connections.json`) é uma
pasta local que é um repositório git: com `remote_url`, um clone de verdade (GitHub ou outro
remote); sem `remote_url`, um repositório só local (`git init`). Não há conexão implícita nem
padrão automática: sem nenhuma cadastrada, toda operação levanta `NoConnectionError` dizendo
para criar uma com `connection_create(name, path[, remote_url])` — a única porta de criação
(a API e a UI só listam, editam, testam, definem a padrão e apagam).

- Cada item vira um arquivo Markdown com frontmatter YAML em
  `<workspace-slug>/<project-slug>/<key>.md` (sem key: `.../_sem-key/<id>.md`) — serialização em
  `services/item_file.py` (`serialize_item`/`parse_item_file`). Workspaces, projects, subjects,
  tags e labels sem item ficam em arquivos `.knowledge.yaml`.
- `storage/files.py` (`FileStore`) lê a pasta e guarda um cache por arquivo (data e tamanho);
  `refresh()` só re-lê o que mudou, então mudanças feitas por fora (editor, `git pull`) valem.
- `services/brain.py`: `Snapshot` é a leitura de um momento; `Draft` acumula mudanças em
  memória e `Brain.commit` grava o conjunto de arquivos e publica pelo git numa publicação só.
- `services/git_repo_service.py` (`GitRepoService`) é o único lugar (com `gh_cli.py`) que chama
  `git`/`gh`, sempre via lista de argumentos (nunca `shell=True`): `ensure_clone` (clona ou
  `git init` na primeira vez), `pull`, `sync` (compara `ls-remote` com o HEAD local; só puxa se
  mudou), `publish` (escreve, comita e — em modo `pr` — abre PR ou Issue), `ensure_workflow`
  (grava `.github/workflows/validate-items.yml` + script de validação: sem segredo, sem key
  duplicada, roda em cada PR) e `ensure_codeowners`.
- `review_mode`, por conexão: `direct` comita (e empurra, se há remote) na branch principal
  na mesma chamada de `item_save`/`item_delete`/`relation_delete`; `pr` escreve numa branch nova
  e abre um Pull Request (ou uma Issue, sem permissão de push) — a mudança aparece depois que o
  PR for mergeado e `repo(action="sync")` (ou o hook de início de sessão) rodar.
- Escritas concorrentes: `storage/access.py` dá uma trava por conexão dentro do processo (UI e
  MCP dividem o mesmo `FileStore`) e uma trava entre processos por pasta, em `<home>/locks/`.

Segredos (`type == "secret"`) entram no arquivo só com metadados: `item_file.serialize_item`
recusa um secret com valor. O valor cifrado mora em `<pasta-da-conexão>/.secrets/<item_id>.enc`,
coberto por um `.gitignore` gerenciado (`secret_service.py`) — nunca entra no git; só
`has_value` é rastreável.

O home (`KNOWLEDGE_OS_HOME`, padrão `~/.knowledge-os`) guarda só estado desta máquina:
`connections.json`, `repos.json`, `usage/`, `locks/`, `pending.jsonl` e marcas pequenas.

## Peças que importam

| Peça | Como funciona | Por quê |
|---|---|---|
| Uma ferramenta por verbo (`knowledge_os/mcp/tools.py`) | `workspace_*`, `project_*`, `subject_*`, `tag_*`, `label_*`, `connection_*`; só `repo` agrupa link/list/unlink/sync em `action=` | nomes claros e argumentos pequenos por ferramenta |
| `item_save` (`ItemService.save`) | lote atômico; `key` → upsert, `id` → update, sem nenhum → create + `similar`; `id` + `workspace`/`project`/`subject` novos → move o item; relações por id ou key; tudo vira uma publicação git | o fechamento de uma mudança grava tudo numa chamada, sem duplicar, e já fica versionado |
| Busca (`storage/search.py`) | índice invertido em memória, mantido pelo `FileStore`; sem acento, radical PT-BR, prefixo; AND e, se vazio, OR; BM25 com pesos por campo | acerto sem embeddings, sem custo de modelo e sem nada para reconstruir |
| Pacote de contexto (`ContextService`) | project do repositório + `Geral` do workspace + `Global/Geral`; seções por tipo; regras com `scope_paths` só quando os paths casam; corta no orçamento e lista o omitido | o agente começa sabendo o essencial gastando ~1–1,5 mil tokens |
| Ligação de repositório de código (`RepoService`, `repos.json`) | chave = remote do git normalizado (ou `path:` + raiz) → conexão/workspace/project; `candidate_match` recusa criar workspace/project novo quando o nome parece (mas não é igual a) um já existente — exige `confirm_new=True` ou o nome exato | o mesmo repositório em qualquer pasta ou máquina acha o mesmo conhecimento, sem duplicar por erro de grafia |
| Serialização item↔arquivo (`item_file.py`) | item ↔ Markdown com frontmatter YAML; recusa serializar `secret` com valor; telemetria de uso fica em `<home>/usage/`, nunca no arquivo | o arquivo versionado é só o que faz sentido revisar num diff |
| Ciclo de vida | `ephemeral` expira (`ttl_days`); `supersedes` marca o alvo `superseded`; `deprecated` sai da busca | o contexto não acumula lixo nem conselho velho |
| `secret_guard` / `secret_service` | `secret_guard`: padrões de chaves, tokens, JWT, `password=`, URL com senha (placeholders passam) recusam itens comuns; `secret_service`: segredo vira item sem valor, preenchido só pela UI local, cifrado em arquivo fora do git | o cérebro é lido em toda sessão e publicado em git; segredo ali vaza para todo agente e para o histórico |
| CLI leve (`knowledge_os/cli.py`) | subcomandos do cérebro não importam fastmcp; erro vira aviso; grava a fila offline `<home>/pending.jsonl` (entradas com `repo`) | o hook roda em toda sessão e nunca pode travá-la |
| Manutenção diária (`services/maintenance.py`) | no máximo uma vez por dia, apaga os `ephemeral` vencidos de cada conexão ativa e publica | o histórico é o do git: cada remoção é um commit, sem cópia de segurança à parte |

## Modelo de dados

`Workspace` 1─N `Project` 1─N `Subject` (opcional) 1─N `Item` (N─N `Tag`, `Label`; `Relation`
entre itens, guardada no frontmatter do item de origem). Workspace, project e subject têm como id
o slug do nome (que é também o nome da pasta); itens mantêm o UUID do frontmatter. Um vínculo em
`repos.json` liga a chave do repositório de código (do usuário) a conexão/workspace/project —
não confundir com a conexão, que é o repositório git onde o conhecimento é publicado. `Item` tem
`key` (única por project, nunca por subject), `type`, `memory_class`, `status`, `scope_paths`,
`keywords`, `source`, `ttl_days`, `importance` e `confidence`.

## Estrutura

```
src/
└── knowledge_os/     pacote instalável (src layout)
    ├── cli.py            ponto de entrada `knowledge-mcp`
    ├── main.py           servidor FastMCP e `ui`
    ├── config.py         home, connections.json (ConnectionConfig: path, remote_url, review_mode)
    ├── mcp/              tools.py, INSTRUCTIONS.md
    ├── services/         regras de negócio: brain.py, item_service.py, git_repo_service.py,
    │                     item_file.py, secret_service.py, gh_cli.py...
    ├── storage/          access.py, files.py, search.py, local_state.py
    ├── schemas/          Pydantic v2
    └── api/              FastAPI da UI (rotas + front estático Alpine.js, sem build)
tests/                unitários, serviços, ferramentas via Client em memória, stdio e CLI
```
