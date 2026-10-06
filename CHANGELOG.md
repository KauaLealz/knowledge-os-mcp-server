# Changelog

## Unreleased

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

### Adicionado

- `knowledge-mcp --migrate-v2`: migração one-shot (nunca automática) de um banco com o schema
  antigo (`domains`/`domain_id`/`project_links`/`project_key`) para o novo. Faz backup antes no
  SQLite; em Postgres/MySQL avisa para tirar um snapshot externo antes de confirmar.

### Quebra de compatibilidade

- O formato do ZIP de `backup export`/`import` mudou junto com o rename de schema — **não há
  shim de leitura do formato antigo**; um backup feito antes desta mudança precisa passar por
  `--migrate-v2` no banco de origem antes de ser exportado de novo.
- Toda ferramenta, parâmetro ou flag de CLI que usava os nomes antigos (`domain`, `project` como
  vínculo de repositório, perfis de ferramenta) mudou de nome ou de forma. Quem tem integração
  própria com o MCP ou com a CLI do `knowledge-mcp` precisa revisar e ajustar as chamadas.
