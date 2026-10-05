# Segundo cérebro (Knowledge OS)

Memória durável entre sessões e projetos: regras, decisões e o porquê, procedimentos,
contexto e aprendizados. Busque antes de supor; grave o que vale para depois.

**Ler**
- Início de sessão: o contexto do projeto costuma vir injetado. Se não veio, ou ao passar a
  mexer em outra área, chame `context_get(project=".", paths=[arquivos])`.
- Uma consulta basta: `context_get` com `paths`/`query` já traz, em foco, o começo do content
  dos itens que casam. Dúvida pontual: `item_search(query)` (busca só o projeto da pasta;
  `everywhere=True` para todos) → resumos; `item_get(keys=[...])` só se faltar detalhe. Busca
  vazia não prova ausência: tente sinônimos.

**Gravar** — tudo por `item_save`, em lote, numa chamada
- Use `key` estável (`regra/...`, `decisao/...`, `proc/...`, `gotcha/...`): grava de novo sem
  duplicar. Com `id`, atualiza; sem key nem id, cria e avisa `similar`.
- Um conhecimento por item; `summary` em 1–2 frases (é o que aparece no contexto).
- `type`: rule (sempre/nunca), insight (decisão e porquê), procedure (passo a passo), pattern,
  knowledge (fato, gotcha), context (pano de fundo), task (plano de uma mudança; `status: done`
  ao concluir).
- `memory_class`: grave `working`; subir para `longterm`/`canonical` só com o "sim" do usuário.
- Regra de parte do código: `scope_paths` (globs). Origem em `source` (mudança, commit).
  Sinônimos em `keywords` (a palavra `sensivel` marca área de risco). Substituiu algo: `relations: [{type: "supersedes", target: key}]`.
- Nunca grave segredos (são recusados) nem dados pessoais.
- Não é item: bug ou dívida (é trabalho), andamento ("ainda falta…"), medição datada, número de
  linha (use classe ou símbolo), id de tarefa. Ambiente da máquina e regra geral de ferramenta vão
  para `Global`. `scope_paths` o mais estreito possível; `sensivel` só em auth, pagamento, dados
  pessoais, tenant e segredos.

**Projeto sem ligação:** sugira ao usuário rodar `/plumb-setup` (ou `project_link(project=".")`, sem
workspace: cada projeto tem o seu, com o nome do repositório; `Global` é só para o que vale em todos).
**Servidor fora do ar:** siga o trabalho e avise; o Plumb guarda o que gravaria em
`~/.knowledge-os/pending.jsonl` (uma entrada por linha, com `project`).

**Administração** (perfil `all`)
- `structure_list` (árvore workspaces → domains), `structure_delete` (preview e depois
  `confirm=True`), `item_delete`, `relation_delete`: destrutivos só com pedido do usuário.
- `vocabulary` (tags e labels), `backup_export` / `backup_import` (ZIP em `<home>/exports`),
  `artifact_attach` / `artifact_get`.
- Conexões com outros bancos (Postgres, MySQL), `schema_sync` e migração entre bancos ficam na
  UI: `knowledge-mcp ui`. Senhas nunca passam pela conversa.
