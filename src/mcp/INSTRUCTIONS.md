# Segundo cérebro (Knowledge OS)

Memória durável entre sessões e projetos: regras, decisões e o porquê, procedimentos,
contexto e aprendizados. Busque antes de supor; grave o que vale para depois.

**Ler**
- Início de sessão: o contexto do projeto costuma vir injetado. Se não veio, ou ao passar a
  mexer em outra área, chame `context_get(project=".", paths=[arquivos])`.
- Dúvida pontual: `item_search(query, project=".")` → resumos; `item_get(keys=[...],
  project=".")` só se o resumo não bastar. Busca vazia não prova ausência: tente sinônimos.

**Gravar** — tudo por `item_save`, em lote, numa chamada
- Use `key` estável (`regra/...`, `decisao/...`, `proc/...`, `gotcha/...`): grava de novo sem
  duplicar. Com `id`, atualiza; sem key nem id, cria e avisa `similar`.
- Um conhecimento por item; `summary` em 1–2 frases (é o que aparece no contexto).
- `type`: rule (sempre/nunca), insight (decisão e porquê), procedure (passo a passo), pattern,
  knowledge (fato, gotcha), context (pano de fundo).
- `memory_class`: grave `working`; subir para `longterm`/`canonical` só com o "sim" do usuário.
- Regra de parte do código: `scope_paths` (globs). Origem em `source` (mudança, commit).
  Sinônimos em `keywords`. Substituiu algo: `relations: [{type: "supersedes", target: key}]`.
- Nunca grave segredos (são recusados) nem dados pessoais.

**Projeto sem ligação:** sugira ao usuário rodar `/plumb-setup` (ou `project_link`).
**Servidor fora do ar:** siga o trabalho e avise; o Plumb guarda o que gravaria em
`.plumb/pending-brain.jsonl`.

**Administração** (perfil `all`)
- `structure_list` (árvore workspaces → domains), `structure_delete` (preview e depois
  `confirm=True`), `item_delete`, `relation_delete`: destrutivos só com pedido do usuário.
- `vocabulary` (tags e labels), `backup_export` / `backup_import` (ZIP em `<home>/exports`),
  `artifact_attach` / `artifact_get`.
- Conexões com outros bancos (Postgres, MySQL), `schema_sync` e migração entre bancos ficam na
  UI: `knowledge-mcp ui`. Senhas nunca passam pela conversa.
