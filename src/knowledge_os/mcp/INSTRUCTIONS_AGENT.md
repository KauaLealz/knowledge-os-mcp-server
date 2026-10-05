# Segundo cérebro (Knowledge OS)

Memória durável entre sessões e projetos: regras, decisões e o porquê, procedimentos,
contexto e aprendizados. Busque antes de supor; grave o que vale para depois.

**Ler**
- O contexto do projeto costuma vir injetado no início. Ao mexer numa área, uma consulta:
  `context_get(project=".", paths=[arquivos], query=tema)` traz em foco o que casa.
- Dúvida pontual: `item_search(query)` (só o projeto; `everywhere=True` para todos), e
  `item_get(keys=[...])` só se faltar detalhe. Busca vazia não prova ausência: tente sinônimos.

**Gravar** — `item_save`, em lote, numa chamada
- `key` estável (`regra/`, `decisao/`, `proc/`, `padrao/`, `gotcha/`, `contexto/`): regrava sem duplicar.
- Um conhecimento por item; `summary` em 1–2 frases com o porquê (é o que o contexto mostra).
- `type`: rule, insight (decisão e porquê), procedure, pattern, knowledge (armadilha do código),
  context, task (plano de mudança; `status: done` ao concluir).
- `scope_paths` o mais estreito possível; `source` = commit ou mudança; `keywords` = 4–8
  sinônimos; `sensivel` só em auth, pagamento, dados pessoais, tenant e segredos.
- Não é item: bug ou dívida, andamento, medição datada, número de linha, id de tarefa.
  Ambiente da máquina e regra geral de ferramenta vão para o workspace `Global`.
- Nunca segredos (são recusados) nem dados pessoais.

**Projeto sem ligação:** sugira `/plumb-setup` (ou `project_link(project=".")`, sem workspace:
cada projeto tem o seu; `Global` é para o que vale em todos).
**Servidor fora do ar:** siga e avise; o que gravaria vai para `~/.knowledge-os/pending.jsonl`
(uma entrada por linha, com `project`).
