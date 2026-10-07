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

### Quebra de compatibilidade

- O formato do ZIP de `backup export`/`import` mudou junto com o rename de schema — **não há
  shim de leitura do formato antigo**; um backup feito antes desta mudança precisa passar por
  `--migrate-v2` no banco de origem antes de ser exportado de novo.
- Toda ferramenta, parâmetro ou flag de CLI que usava os nomes antigos (`domain`, `project` como
  vínculo de repositório, perfis de ferramenta) mudou de nome ou de forma. Quem tem integração
  própria com o MCP ou com a CLI do `knowledge-mcp` precisa revisar e ajustar as chamadas.
