# Segundo cérebro (Knowledge OS)

Memória durável: regras, decisões e o porquê, procedimentos, contexto e aprendizados.
Workspace = contexto (empresa, cliente, Pessoal); domain = repositório; `Geral` do workspace =
o que vale para os repos dele; workspace `Global` = o que vale para o usuário em qualquer lugar.

**Ler:** o contexto vem injetado no início. Ao mexer numa área, `context_get(project=".",
paths=[arquivos], query=tema)`. Dúvida: `item_search(query)`, `item_get(keys=[...])` se faltar.

**Quando gravar** (`item_save`, em lote, `key` estável — regrava sem duplicar):
- Na hora: o usuário enuncia regra, decisão ou preferência.
- Ao destravar algo não óbvio: `knowledge` com sintoma, causa e o que fazer.
- Ao fechar uma mudança: decisões (`insight`, com a alternativa descartada), primeira solução
  de um tipo de problema (`pattern`, com o arquivo-modelo), passos que vão se repetir
  (`procedure`), o que custou tempo (`knowledge`).
- `rule` = sempre/nunca verificável num diff; `context` = o que o projeto é (poucos itens).
- Antes de criar, procure: atualize pela mesma key; se contradiz, `supersedes`.
- `summary` de 1–2 frases com o porquê; `scope_paths` estreito; `sensivel` só em auth,
  pagamento, dados pessoais, tenant e segredos.
- Não é item: bug ou dívida, andamento, medição datada, número de linha, id de tarefa, o que se
  redescobre lendo um arquivo. Ambiente da máquina e ferramenta em geral vão para o `Global`.
- Segredo (token, senha): item `secret` `segredo/<nome>` sem valor; passe ao usuário o
  `fill_url` da resposta (ele preenche na UI). Nunca peça o valor no chat. Usar:
  `knowledge-mcp run --env VAR=segredo/<nome> -- <comando>`. Dado pessoal: nunca.

**Sem ligação:** `/plumb-setup` ou `project_link(project=".")`. **Fora do ar:** siga, avise e
guarde em `~/.knowledge-os/pending.jsonl` (uma entrada por linha, com `project`).

**Administração** (perfil `all`)
- `structure_list` (árvore workspaces → domains), `structure_delete` (preview e depois
  `confirm=True`), `item_delete`, `relation_delete`: destrutivos só com pedido do usuário.
- `vocabulary` (tags e labels), `backup_export` / `backup_import` (ZIP em `<home>/exports`),
  `artifact_attach` / `artifact_get`.
- Conexões com outros bancos (Postgres, MySQL), `schema_sync` e migração entre bancos ficam na
  UI: `knowledge-mcp ui`. Senhas nunca passam pela conversa.
