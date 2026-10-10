# Changelog

## 0.3.0 — Unreleased

Redesenho do modelo de conhecimento (v2). Não há compatibilidade nas ferramentas, na API nem na
UI; só a **leitura de arquivos** traduz o formato antigo (ver "Migração").

### Alterado (quebra de compatibilidade)

- **Cinco tipos, com subtipos.** `rule` (`code`, `pattern`, `security`, `business`, `process`,
  `decision`), `howto` (`procedure`, `troubleshoot`), `context` (`product`, `map`, `stack`,
  `glossary`, `environment`), `spec` (`change`, `setup`, `dream`) e `secret`. Substituem os tipos
  `rule`, `insight`, `procedure`, `pattern`, `knowledge`, `context`, `task` e `secret` anteriores.
  Key no padrão `<tipo>/<nome>` (fora dele grava com aviso); o segredo passa a usar `secret/<nome>`.
- **Alcance por `scope`.** `scoped` (só o project), `workspace` ou `global`, definido no item, no
  subject, no project ou no workspace, com herança nessa ordem (nada explícito = `scoped`). O
  item mora onde foi salvo e vale onde o scope manda; `workspace_update`, `project_update` e
  `subject_update` aceitam `scope=` e mudam o alcance de tudo que herda, sem mover arquivo. Busca,
  pacote, grafo, `item_get` e `item_save` usam o mesmo resolvedor (`services/scope.py`): mesmo
  project 1.0, scope `workspace` de outro project do workspace 0.85, `global` de fora 0.7.
- **Status:** `active`, `review`, `archived` (só `spec`: também `draft` e `done`); `expired` é
  derivado do `ttl_days`. Campo novo `origin` (`user`, `code`, `agent`), `links`
  (`{title, url}`), `verified_at` e `verified_commit`.
- **`context_get` removido.** O pacote do projeto vem do hook (`knowledge-mcp context`); sob demanda,
  `item_search(repo=".")` sem consulta devolve o essencial em grupos (segurança, regras, contexto,
  specs). A palavra `sensivel` em `keywords` perdeu o efeito: sensível é `rule/security`.
- **Labels removidos** (`label_list`, `label_create`, `label_delete`); as tags passam a ser
  gerenciadas. Saem também `workspace_rename`, `project_rename` e `subject_rename` (viram `*_update`
  com `new_name`).
- **Campos removidos:** `memory_class`, `importance`, `confidence`, `labels`, `level` e a promoção
  de classe de memória. Item temporário continua possível com `ttl_days`, mas o servidor não
  apaga mais nada sozinho (a manutenção diária saiu): o vencido some da busca e aparece em
  `status=["expired"]`.
- **Ferramentas em lote.** `item_save`, `item_get`, `item_delete`, `item_feedback`,
  `relation_create` e `relation_delete` recebem listas (até 20; `item_get` e `item_delete` por
  `keys`/`ids`), atômicas. `item_save` deixou de aceitar relações embutidas e de aceitar campo
  desconhecido (erro com a lista dos válidos).
- **`item_search` explicada.** Parâmetros novos: `queries` (até 5), `paths`, `scope`, `subtypes`,
  `origin`, `workspace`, `everywhere`; cada resultado traz `scope`, `where`, `matched_in` e
  `snippet` (com `paths`, também `excerpt` e `scope_paths`). Relevância BM25 com pesos por campo
  (título 6, keywords 4, summary 3, tags 3, subtipo 2, content 1), identificadores indexados pelas
  partes (camelCase, snake_case, pontos) e idf sempre positivo (variante do Lucene), de modo que
  um termo presente em mais da metade do acervo ainda ranqueia pelos campos.
- **API e UI** no modelo novo: tipos com subtipo, scope (com o herdado), marca de revisão, `links`,
  `origin`, tags com contagem e o caminho da conexão; sem labels, classe de memória, importância
  nem confiança. O grafo da ficha do item mostra também relações com outros projects
  (`GET /api/items/{id}/graph` ignora o alcance).

### Adicionado

- **32 ferramentas**: `item_delete` em três passos (candidatos,
  prévia, `confirm`), **`item_feedback`** (`helped`, `irrelevant`, `wrong`, `outdated`,
  `verified`), **`item_graph`** (vizinhança até 3 saltos, com `truncated` e `total_by_hop`),
  **`tag_update`** (renomeia ou mescla), `tag_create`/`tag_delete` com prévia, e
  `workspace_*`/`project_*`/`subject_*` com `list`, `create`, `update`, `merge` e `delete`.
  Contrato conferido por teste: nomes, docstrings (uso, retorno, exemplo) e os documentos só
  citam ferramentas que existem.
- **Sinais de uso** locais (fora do git): `shown`, `opened`, `helped`, `irrelevant`, `wrong`,
  `outdated`, `verified` por item e as buscas que voltaram vazias (`searches/<conexão>.jsonl`).
  Entram no ranking e no relatório.
- **`knowledge-mcp report --json`**: nunca abertos há 60 dias, em revisão há mais de 7, muito
  irrelevantes, buscas vazias e tags sem uso.
- **Pacote do hook v2** (`knowledge-mcp context`): seções Em foco, Em revisão, Segurança, Regras
  por subtipo, Contexto, Como fazer, Specs ativas, Segredos e Regras com escopo, com a origem
  nos itens de fora do project.
- **`health_check`** devolve as conexões e os arquivos que não leram (`parse_errors`).
- Instruções do MCP (`mcp/INSTRUCTIONS.md`) geradas da taxonomia do `model.py`.

### Corrigido

- Nota de `wrong`/`outdated` num item de `content` vazio deixava linhas em branco no início, e
  notas seguidas empilhavam linhas em branco; agora a nota entra sem linha em branco inicial e
  notas consecutivas ficam na mesma citação.
- O idf do BM25 zerava a relevância em acervo pequeno (termo em mais da metade dos itens).

### Removido

- `context_get`, `label_*`, `*_rename`, `memory_service` (promoção de classe), `label_service` e a
  manutenção diária de itens `ephemeral`; os campos `memory_class`, `importance`, `confidence` e
  `labels` e as rotas de labels da API (agora 404).

### Migração

Não há script. Ao **ler** um arquivo no formato antigo, o servidor o traduz: `insight` → `rule/decision`;
`procedure` → `howto/procedure`; `knowledge` → `howto/troubleshoot` com status `review`; `pattern` →
`rule/pattern`; `task` → `spec`; `rule` com `sensivel` em `keywords` → `rule/security`; status
`superseded`/`deprecated` → `archived`; `labels` somadas às `tags`; `memory_class`, `importance`
e `confidence` descartados (um `ephemeral` mantém o `ttl_days`); `origin` ausente vira `user` em
arquivo antigo e `agent` nos novos. A regravação de cada item já sai no formato novo.

## Antes da 0.3.0 (sem banco de dados)

### Alterado (quebra de compatibilidade) — sem banco de nenhum tipo

- **Armazenamento só em arquivos.** O servidor lê e grava apenas nos arquivos da pasta de cada
  conexão (um repositório git): itens em Markdown com frontmatter YAML, `.knowledge.yaml` para
  workspaces/projects/tags/labels e segredos cifrados em `.secrets/`. Saíram o SQLite (catálogo
  e índices por conexão), o FTS5, o SQLAlchemy e o SQLCipher; a busca é em memória sobre os
  arquivos. Cada escrita é um commit; o histórico e o backup são os do git.
- **Sem conexão automática.** Não existe mais o catálogo `default`: `connections.json` começa
  vazio (`default: null`) e, sem conexão, toda operação responde "Nenhuma conexão configurada.
  Crie uma com connection_create(name, path[, remote_url])."; a tela inicial da UI explica o
  mesmo.
- **Criação de conexão só pelo MCP** (`connection_create`). A UI lista (com o caminho da pasta,
  o remote, o modo, a padrão e o estado da pasta), edita, testa, define a padrão e apaga, mas não
  cria. `GET /api/connections` ganhou `path_exists` e `is_git_repo`.
- `~/.knowledge-os` guarda só estado da máquina: `connections.json`, `repos.json`, `usage/`,
  `locks/` e `pending.jsonl`.

### Removido

- Rota `POST /api/connections` (criação pela API) e o seletor de pasta da UI de conexões.
- Rota `POST /api/connections/{id}/schema-sync` e o `schema_sync`.
- Ferramentas `backup` (export/import em ZIP), `artifact` e `vocabulary` (substituída por
  `tag_*`/`label_*`).
- Flags `--check-db`, `--bootstrap` e `--migrate-v2` do `knowledge-mcp`, e os alvos
  `make bootstrap`/`make check-db`.
- Variáveis `MCP_DB_PATH` e `MCP_DB_KEY` e o extra `crypto`.


### Corrigido

- Push rejeitado (non-fast-forward) no mesmo arquivo, em publish concorrente de `direct`,
  deixava o clone preso num conflito de `rebase` — qualquer publish seguinte na mesma
  connection passava a falhar até alguém rodar `git rebase --abort` manualmente. Trocado por
  `reset --hard` + reescrita dos arquivos (last-write-wins), que nunca entra em conflito de
  merge de texto.

### Limitações conhecidas (storage em git)

- Se a publicação no git tiver sucesso mas a transação do índice SQLite falhar logo depois
  (esgotando as tentativas de `run_with_retry`), o item fica publicado no repositório mas
  ausente do índice — sem compensação automática; precisa de um `repo(action="sync")` manual
  para reconciliar. Janela estreita (falha teria que ocorrer bem depois do commit/push já
  confirmado), mas sem detecção automática hoje.
- `connection_service.py` chama `ensure_codeowners([])` sempre com lista vazia — o mecanismo de
  CODEOWNERS por pasta existe e é testado, mas nenhuma connection gera regras de verdade ainda;
  fica para quando houver um jeito de configurar quem aprova cada pasta.
- Leitura não trava explicitamente na branch principal — o índice reflete o que estiver
  checked out no clone local, sem uma trava contra ler de uma branch não publicada.

### Alterado (quebra de compatibilidade)

- **`Domain` renomeado para `Project`.** O nível que representava "um repositório dentro de um
  workspace" (tabela `domains`, coluna `domain_id`, parâmetro `domain`/`project` solto nas
  ferramentas antigas) agora se chama `Project` em todo lugar: schema, ferramentas MCP, CLI e UI.
- **O antigo conceito de `project` (vínculo repositório↔workspace/domain) renomeado para
  `Repo`.** `ProjectLink`/`ProjectService` viram `RepoLink`/`RepoService`; a tabela
  `project_links` virou `repo_links`, a coluna `project_key` virou `repo_key`. A ferramenta
  `project_link` virou `repo(action="link")` (com `list` e `unlink` também).
- **Camada `Subject` nova.** Agrupador opcional de items dentro de um `Project` (ex.:
  "pagamentos" dentro do project "app"). Hierarquia agora é `Workspace → Project → Subject
  (opcional) → Item`. `item_key` continua único por `Project`, nunca por `Subject`.
- **Mover um item por `id`.** `item_save` com `id` e `workspace`/`project`/`subject` novos na
  mesma entrada move o item de lugar em vez de recriar (preserva `id`, `created_at`,
  `access_count`, tags, labels, relations e artifacts).
- **15 ferramentas antigas consolidadas em 14, sem conceito de perfil.** Os perfis `agent` (6
  ferramentas) e `all` (+9) foram removidos — qualquer cliente MCP vê sempre as mesmas 14
  ferramentas. A variável de ambiente `KNOWLEDGE_OS_TOOLSET` não existe mais. `workspace`,
  `project`, `subject`, `repo`, `artifact` e `backup` usam um parâmetro `action=` para agrupar
  o que antes eram ferramentas separadas:
  - `structure_list`/`structure_delete` → `workspace(action=...)` / `project(action=...)`
  - `project_link` → `repo(action="link"|"list"|"unlink")`
  - `artifact_attach`/`artifact_get` → `artifact(action="attach"|"get")`
  - `backup_export`/`backup_import` → `backup(action="export"|"import")`
  - `item_delete`, `relation_delete`, `vocabulary`, `item_search`, `item_get`, `item_save`,
    `context_get`, `health_check` seguem como ferramentas próprias (com `repo=` no lugar de
    `project=`, e `item_search`/`item_get` com o novo parâmetro `subject=`).
- **`candidate_match` em `repo(action="link")`.** Quando o nome de workspace/project candidato
  parece (mas não é igual a) um já existente, o link não cria nada: devolve
  `{status: "candidate", candidate_match: {...}}` e exige `confirm_new=True` (ou o nome exato)
  para seguir — evita workspace/project duplicado por erro de grafia.
- **CLI:** a flag que apontava o caminho do repositório mudou de `--project` para `--repo`; a
  flag que apontava o nome do nível (era "domain") mudou de `--domain` para `--project`. Ex.:
  `knowledge-mcp link --repo . --workspace Polara --project projpro`.
- **`item_save` em modo `pr` não devolve mais `{action, id, ...}` na hora.** Para uma
  connection com `review_mode="pr"`, salvar um item não secreto abre (ou atualiza) um Pull
  Request com o arquivo serializado e devolve `{status: "pending_review", pr_url}` — ou
  `{status: "issue_opened", issue_url}` se a connection não tem permissão de push no remote
  — em vez do formato de sempre. O índice (SQLite) só é atualizado depois que o PR for
  mergeado e `repo(action="sync")` (ou o hook de início de sessão) puxar a mudança. Em modo
  `direct` (padrão) o contrato não muda: publica no repositório e atualiza o índice na mesma
  chamada. `item_delete` segue o mesmo contrato para as duas remoções (a publicação some do
  repositório antes do índice refletir, ou fica pendente de PR).

### Adicionado

- `knowledge-mcp --migrate-v2`: migração one-shot (nunca automática) de um banco com o schema
  antigo (`domains`/`domain_id`/`project_links`/`project_key`) para o novo. Faz backup antes no
  SQLite; em Postgres/MySQL avisa para tirar um snapshot externo antes de confirmar.
- **Storage de items vira arquivo versionado no repositório da connection.** Todo item não
  secreto salvo numa connection com repositório git configurado (`repo(action="link")` já
  cuidava do vínculo; a connection em si é criada por `ConnectionService`) agora também vira
  um arquivo Markdown com frontmatter YAML nesse repositório (`services/item_file.py`),
  publicado via `services/git_repo_service.py` — commit direto na branch principal
  (`review_mode="direct"`) ou PR/Issue de revisão (`review_mode="pr"`). O catálogo (banco
  default, sem connection) continua só no SQLite, sem repositório git. Segredos (`type:
  secret`) nunca são serializados para arquivo — continuam só no índice, como sempre.
- `repo(action="sync")`: sincroniza manualmente o repositório git da connection ativa
  (`{synced: bool}`). O hook de início de sessão (`knowledge-mcp context`) já chama isso
  sozinho antes de montar o contexto, tolerando falha de rede ou `gh` ausente sem quebrar a
  sessão.

- **Migração SQLite → Git concluída.** Fecha a refatoração de storage (lotes GS-L1 a GS-L6):
  serializador item↔arquivo, `GitRepoService`/`gh_cli`, connection vira repositório git,
  `item_save`/`item_delete`/`relation_delete` publicando em `direct`/`pr`, segredos sempre em
  arquivo gitignorado (nunca no git nem no índice). README, `docs/ARQUITETURA.md` e
  `docs/MCP_USAGE.md` atualizados para a arquitetura atual.

### Quebra de compatibilidade

- O formato do ZIP de `backup export`/`import` mudou junto com o rename de schema — **não há
  shim de leitura do formato antigo**; um backup feito antes desta mudança precisa passar por
  `--migrate-v2` no banco de origem antes de ser exportado de novo.
- Toda ferramenta, parâmetro ou flag de CLI que usava os nomes antigos (`domain`, `project` como
  vínculo de repositório, perfis de ferramenta) mudou de nome ou de forma. Quem tem integração
  própria com o MCP ou com a CLI do `knowledge-mcp` precisa revisar e ajustar as chamadas.
