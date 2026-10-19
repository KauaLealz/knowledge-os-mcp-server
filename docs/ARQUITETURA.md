# Arquitetura

Voltar ao [README](../README.md). Uso das ferramentas: [MCP_USAGE.md](MCP_USAGE.md). Contrato da
v2: [V2_MVP.md](V2_MVP.md).

## Camadas

```
Agente (Claude Code, Cursor)          Hook de início de sessão      Navegador
   │ MCP stdio                           │ knowledge-mcp context      │ knowledge-mcp ui
   ▼                                     ▼                            ▼
knowledge_os/main.py  FastMCP         knowledge_os/cli.py (sem fastmcp)   knowledge_os/api  FastAPI + static
 └─ mcp/tools.py  32 ferramentas        context · recent · report ·       itens, tags, relações, grafo,
    mcp/instructions.py (INSTRUCTIONS)  pending · link · run              organização, conexões (editar)
   │                                     │                            │
   └──────────────────────┬──────────────┴────────────────────────────┘
                          ▼
knowledge_os/services/   Brain (Snapshot/Draft/commit) · scope · ItemService · RelationService
                graph · TagService · Workspace/Project/SubjectService · ContextService
                RepoService · ConnectionService · GitRepoService (clone/pull/publish/sync)
                item_file (serialização) · secret_service/secret_guard/secret_run/vault
                          ▼
knowledge_os/storage/    access (qual conexão, travas) · files (FileStore) · search (busca em
                         memória) · local_state (repos.json, usage/, searches/)
                          ▼
            Por conexão: uma pasta local que é um repositório git (a única fonte de verdade)

knowledge_os/model.py    taxonomia, valores válidos e validação de entrada: puro, sem I/O
```

Ferramentas são finas: resolvem nomes e repositório para o lugar do item, chamam um service e
devolvem JSON enxuto. As regras de negócio (lote atômico, idempotência por `key`, alcance,
guarda de segredo, publicação git) ficam nos services, e por isso CLI, MCP e UI se comportam
igual.

## `model.py`: a taxonomia numa fonte só

`model.py` é puro (sem I/O, sem importar serviços) e define tudo o que é conjunto fechado: os
cinco tipos e seus subtipos (`TYPES`), `STATUSES` e `SPEC_STATUSES`, `SCOPES`, `ORIGINS`,
`RELATION_TYPES`, `OUTCOMES`, os campos aceitos por `item_save` (`ITEM_FIELDS`,
`LOCATION_FIELDS`), o padrão e os problemas de key (`key_problem`, `key_warnings`) e os avisos
do modelo do `content` por subtipo. `validate_entry(entry)` normaliza e valida uma entrada de
`item_save`, devolve os campos limpos e os avisos, e levanta `ValidationError` com a lista dos
valores válidos. `taxonomy_markdown()` gera as tabelas que entram no `mcp/INSTRUCTIONS.md` (um
teste confere que o arquivo é o que o gerador produz) e que o README reproduz.

## O armazenamento são os arquivos da conexão

Cada conexão (`ConnectionConfig` em `config.py`, cadastrada em `<home>/connections.json`) é uma
pasta local que é um repositório git: com `remote_url`, um clone de verdade (GitHub ou outro
remote); sem `remote_url`, um repositório só local (`git init`). Não há conexão implícita nem
padrão automática: sem nenhuma cadastrada, toda operação levanta `NoConnectionError` dizendo
para criar uma com `connection_create(name, path[, remote_url])` — a única porta de criação
(a API e a UI só listam, editam, testam, definem a padrão e apagam).

- Cada item vira um arquivo Markdown com frontmatter YAML em
  `<workspace-slug>/<project-slug>/<key>.md` (sem key: `.../_sem-key/<id>.md`) — serialização em
  `services/item_file.py` (`serialize_item`/`parse_item_file`). Descrição e `scope` de
  workspaces, projects e subjects, e o vocabulário de tags, ficam em arquivos `.knowledge.yaml`.
- **Leitura de arquivo antigo.** `parse_item_file` é o único ponto de compatibilidade: um
  arquivo no formato anterior é traduzido na leitura (tipos e status antigos para os de hoje,
  `labels` somadas às `tags`, campos que saíram descartados) e a regravação já sai no formato
  atual. Não há script de migração.
- `storage/files.py` (`FileStore`) lê a pasta e guarda um cache por arquivo (data e tamanho);
  `refresh()` só re-lê o que mudou, então mudanças feitas por fora (editor, `git pull`) valem.
  Arquivo que não lê vai para `parse_errors` (visível em `health_check`) e não derruba o resto.
- `services/brain.py`: `Snapshot` é a leitura de um momento (com o scope efetivo de cada item,
  pela herança subject → project → workspace); `Draft` acumula mudanças em memória e
  `Brain.commit` grava o conjunto de arquivos e publica pelo git numa publicação só.
- `services/git_repo_service.py` (`GitRepoService`) é o único lugar (com `gh_cli.py`) que chama
  `git`/`gh`, sempre via lista de argumentos (nunca `shell=True`): `ensure_clone` (clona ou
  `git init` na primeira vez), `pull`, `sync` (compara `ls-remote` com o HEAD local; só puxa se
  mudou), `publish` (escreve, comita e — em modo `pr` — abre PR ou Issue), `ensure_workflow`
  (grava `.github/workflows/validate-items.yml` + script de validação: sem segredo, sem key
  duplicada, roda em cada PR) e `ensure_codeowners`.
- `review_mode`, por conexão: `direct` comita (e empurra, se há remote) na branch principal na
  mesma chamada; `pr` escreve numa branch nova e abre um Pull Request (ou uma Issue, sem
  permissão de push) — a mudança aparece depois que o PR for mergeado e `repo(action="sync")` (ou
  o hook de início de sessão) rodar.
- Escritas concorrentes: `storage/access.py` dá uma trava por conexão dentro do processo (UI e
  MCP dividem o mesmo `FileStore`) e uma trava entre processos por pasta, em `<home>/locks/`.

Segredos (`type == "secret"`) entram no arquivo só com metadados: `item_file.serialize_item`
recusa um secret com valor. O valor cifrado mora em `<pasta-da-conexão>/.secrets/<item_id>.enc`,
fora do git (`.git/info/exclude`) — só `has_value` é rastreável.

O home (`KNOWLEDGE_OS_HOME`, padrão `~/.knowledge-os`) guarda só estado desta máquina:
`connections.json`, `repos.json`, `usage/<conexão>.json` (contadores `shown`, `opened`, `helped`,
`irrelevant`, `wrong`, `outdated`, `verified` por item), `searches/<conexão>.jsonl` (buscas que
voltaram vazias), `locks/` e `pending.jsonl`.

## Alcance (`services/scope.py`)

O resolvedor único do alcance; busca, pacote de contexto, grafo, `item_get` e `item_save` usam só
ele. Dado o `viewpoint` `(workspace, project)` do repositório ligado (ou nenhum, para pasta não
ligada), `distance` devolve o peso do item: 1.0 no mesmo project (qualquer scope); 0.85 em outro
project do mesmo workspace com scope efetivo `workspace` ou `global`; 0.7 de outro workspace com
`global`; `None` (invisível) no resto. `reach` lista o que está no alcance, do mais perto ao mais
longe; `resolve_key` acha uma key pela mesma cadeia (project do repositório primeiro, depois o
resto do alcance) ou por id; `where` diz `workspace/project`.

## Peças que importam

| Peça | Como funciona | Por quê |
|---|---|---|
| Uma ferramenta por verbo (`mcp/tools.py`) | `workspace_*`, `project_*`, `subject_*`, `tag_*`, `connection_*` com `list/create/update/merge/delete`; só `repo` agrupa link/list/unlink/sync em `action=`; cada docstring traz uso, retorno e exemplo | nomes claros e argumentos pequenos por ferramenta |
| `item_save` (`ItemService.save`) | lote atômico de até 20; `key` → upsert, `id` → update (ou move), sem nenhum → create + `similar`; valida por `model.validate_entry`; tudo vira uma publicação git | o fechamento de uma mudança grava tudo numa chamada, sem duplicar, e já fica versionado |
| Busca (`storage/search.py` + `ItemService.search`) | índice invertido em memória; BM25 com pesos por campo (`title` 6, `keywords` 4, `summary` 3, `tags` 3, `subtype` 2, `content` 1) e idf sempre positivo; sem acento, radical PT-BR, prefixo, partes de identificador; AND e, se vazio, OR; `score` = BM25 × distância × `paths` × `review` × sinais de uso | acerto sem embeddings, sem custo de modelo e sem nada para reconstruir; o resultado explica por que veio |
| Sinais de uso (`storage/local_state.py`) | cada resultado soma `shown`; `item_get` e os nós do grafo, `opened`; `item_feedback`, o contador do resultado; busca vazia vai para `searches/` | ranking e relatório de revisão aprendem com o uso, sem sujar o git |
| Relações e grafo (`RelationService`, `services/graph.py`) | relações no frontmatter do item de origem, em lote atômico; o grafo parte de até 5 itens, segue até 3 saltos, ordena os vizinhos por uso e `updated_at` e informa o total real quando corta; `supersedes` arquiva o alvo | a decisão que substitui outra fica ligada a ela, e o agente vê a vizinhança sem abrir tudo |
| Tags gerenciadas (`TagService`) | vocabulário em `.knowledge.yaml`, contagem por item, renomear/mesclar e apagar com prévia | tag não vira sinônimo solto: a nova avisa e sugere a parecida |
| Pacote de contexto (`ContextService`) | pelo alcance do repositório; seções (em foco, revisão, segurança, regras por subtipo, contexto, como fazer, specs, segredos, regras com escopo); corta no orçamento e lista o omitido | o agente começa sabendo o essencial gastando ~1–1,5 mil tokens |
| Relatório (`knowledge-mcp report`) | nunca abertos há 60 dias, em revisão há mais de 7, muito irrelevantes, buscas vazias e tags sem uso | o dream sabe o que revisar sem varrer o acervo |
| Ligação de repositório de código (`RepoService`, `repos.json`) | chave = remote do git normalizado (ou `path:` + raiz) → conexão/workspace/project; `candidate_match` recusa criar workspace/project novo quando o nome parece (mas não é igual a) um já existente — exige `confirm_new=True` ou o nome exato | o mesmo repositório em qualquer pasta ou máquina acha o mesmo conhecimento, sem duplicar por erro de grafia |
| Limpeza (`ItemService.delete`) | sem chaves, lista candidatos por motivo; com chaves, prévia; só `confirm=True` apaga (e leva as relações que apontavam); nunca `origin: "user"`; nada some sozinho | o acervo não acumula lixo, e quem decide é o usuário |
| `secret_guard` / `secret_service` | `secret_guard`: padrões de chaves, tokens, JWT, `password=`, URL com senha (placeholders passam) recusam itens comuns; `secret_service`: segredo vira item sem valor, preenchido só pela UI local, cifrado em arquivo fora do git | o cérebro é lido em toda sessão e publicado em git; segredo ali vaza para todo agente e para o histórico |
| CLI leve (`cli.py`) | subcomandos do cérebro não importam fastmcp; erro vira aviso; grava a fila offline `<home>/pending.jsonl` | o hook roda em toda sessão e nunca pode travá-la |

## Modelo de dados

`Workspace` 1─N `Project` 1─N `Subject` (opcional) 1─N `Item` (N─N `Tag`; `Relation` entre
itens, guardada no frontmatter do item de origem). Workspace, project e subject têm como id o slug
do nome (que é também o nome da pasta); itens mantêm o UUID do frontmatter. Workspace, project e
subject têm `description` e `scope`. Um vínculo em `repos.json` liga a chave do repositório de
código (do usuário) a conexão/workspace/project — não confundir com a conexão, que é o
repositório git onde o conhecimento é publicado.

`Item`: `key` (única por project, nunca por subject), `type`, `subtype`, `scope` (o explícito; o
efetivo vem da herança), `title`, `summary`, `content`, `status`, `tags`, `links` (`{title,
url}`), `scope_paths`, `keywords`, `source`, `origin`, `ttl_days`, `verified_at`,
`verified_commit`, `relations`, `created_at` e `updated_at`.

## API HTTP e UI

`knowledge_os/api` é o FastAPI da UI, em `127.0.0.1`: rotas finas sobre os mesmos services (itens
com `subtype`, `scope` efetivo e herdado, `links` e `origin`; `/tags` com contagem; relações em
lote; grafo no formato do `item_graph`, sem limite de alcance, para mostrar na ficha do item as
relações com outros projects; busca com os filtros novos; workspaces, projects e subjects com
`scope`; conexões), mais o front estático (Alpine.js, sem build) em `api/static`. O valor de um
segredo entra só por `PUT /items/{id}/secret` e nenhuma rota o devolve.

## Estrutura

```
src/
└── knowledge_os/     pacote instalável (src layout)
    ├── cli.py            ponto de entrada `knowledge-mcp`
    ├── main.py           servidor FastMCP e `ui`
    ├── config.py         home, connections.json (ConnectionConfig: path, remote_url, review_mode)
    ├── model.py          taxonomia e validação (puro)
    ├── mcp/              tools.py, instructions.py, INSTRUCTIONS.md (gerado do model.py)
    ├── services/         regras de negócio: brain.py, scope.py, item_service.py, graph.py,
    │                     relation_service.py, tag_service.py, context_service.py,
    │                     git_repo_service.py, item_file.py, secret_service.py, gh_cli.py...
    ├── storage/          access.py, files.py, search.py, local_state.py
    ├── schemas/          Pydantic v2 (entradas finas: o serviço valida)
    └── api/              FastAPI da UI (rotas + front estático)
tests/                unitários, serviços, ferramentas via Client em memória, stdio, CLI e o
                      contrato (as 32 ferramentas, as docstrings, os documentos)
```
