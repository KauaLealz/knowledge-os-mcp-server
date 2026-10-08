# Segundo cérebro (Knowledge OS)

Memória durável: regras, decisões e o porquê, procedimentos e aprendizados.
Workspace = contexto (empresa, cliente, Pessoal); project = repositório; `Geral` do workspace =
o que vale pros repos dele; `Global` = o que vale em qualquer lugar. Subject = assunto opcional
dentro de um project.

**Conexão:** os dados ficam em arquivos numa pasta (repositório git) — a conexão. Sem conexão
nada funciona: crie com `connection_create(name, path[, remote_url])`; `connection_list` e
`connection_delete` (não apaga a pasta). Gerenciar na UI: `knowledge-mcp ui`.
Senhas nunca passam pela conversa.

**Ler:** o contexto vem injetado no início. Ao mexer numa área, `context_get(repo=".",
paths=[arquivos], query=tema)`. Dúvida: `item_search(query)`, `item_get(keys=[...])`.

**Quando gravar** (`item_save`, em lote, `key` estável — regrava sem duplicar):
- Na hora: o usuário enuncia regra, decisão ou preferência.
- Ao destravar algo não óbvio: `knowledge` com sintoma, causa e o que fazer.
- Ao fechar uma mudança: decisões (`insight`, com a alternativa descartada), primeira solução
  de um tipo de problema (`pattern`, com o arquivo-modelo), passos que se repetem
  (`procedure`), o que custou tempo (`knowledge`).
- `rule` = sempre/nunca verificável num diff; `context` = o que o projeto é (poucos itens).
- Antes de criar, procure: atualize pela mesma key; se contradiz, `supersedes`.
- `summary` de 1–2 frases com o porquê; `scope_paths` estreito; `sensivel` em auth,
  pagamento, dados pessoais, tenant e segredos.
- Não é item: bug, andamento, medição datada, id de tarefa. Máquina/ferramenta: `Global`.
- Segredo: item `secret` `segredo/<nome>` sem valor; passe o `fill_url` ao usuário (preenche
  na UI). Nunca peça o valor no chat. Usar: `knowledge-mcp run --env VAR=segredo/<nome> --
  <comando>`. Dado pessoal: nunca.

**Sem ligação:** `/plumb-setup` ou `repo(action="link", repo=".")`. **Fora do ar:** siga, avise
e guarde em `~/.knowledge-os/pending.jsonl`.

**Organização**
- `workspace_*`, `project_*`, `subject_*`: list, create, rename, merge (move o conteúdo de
  `source` pra `target` e apaga `source`), delete (preview sem `confirm`, `confirm=True`
  apaga). Subject delete só desvincula, nunca apaga item.
- `repo(action, repo, workspace, project, confirm_new)`: link cria workspace/project se não
  existirem — a menos que o nome pareça com um já existente (`candidate_match`; repita com
  `confirm_new=True`). list audita vínculos; unlink desfaz um; sync puxa o remote.
- `tag_*`, `label_*` (list, create, delete); `relation_create`/`relation_delete`.
- Destrutivos só com pedido explícito; prefira `status=deprecated` se o histórico importar.
  Tudo é commit no repositório da conexão: dá pra voltar pelo git.
