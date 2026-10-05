# Segundo cérebro (Knowledge OS)

Memória durável entre sessões e projetos: regras, decisões e o porquê, procedimentos,
contexto e aprendizados. Busque antes de supor; grave o que vale para depois.

**Ler**
- Início de sessão: o contexto do projeto costuma vir injetado. Se não veio, ou ao passar a
  mexer em outra área, chame `context_get(project=".", paths=[arquivos])`.
- Dúvida pontual: `item_search(query, project=".")` → resumos; `item_get(key=..., project=".")`
  só se o resumo não bastar. Busca vazia não prova ausência: tente sinônimos.

**Gravar**
- Prefira `item_batch_upsert` ao fechar um trabalho, ou `item_upsert`, sempre com `key` estável
  (`regra/...`, `decisao/...`, `proc/...`, `gotcha/...`) para atualizar em vez de duplicar.
- Um conhecimento por item; `summary` em 1–2 frases (é o que aparece no contexto).
- `type`: rule (sempre/nunca), insight (decisão e porquê), procedure (passo a passo), pattern,
  knowledge (fato, gotcha), context (pano de fundo).
- `memory_class`: grave `working`; `longterm` e `canonical` só com o "sim" do usuário
  (`memory_promote`).
- Regra que vale só para parte do código: `scope_paths` (globs). Cite a origem em `source`
  (mudança, commit). Sinônimos em `keywords`.
- Substituiu algo: novo item + `relation_create(novo, antigo, "supersedes")`.
- Nunca grave segredos (são recusados) nem dados pessoais.

**Projeto sem ligação:** sugira ao usuário rodar `/plumb-setup` (ou `project_link`).
**Servidor fora do ar:** siga o trabalho e avise; o Plumb guarda o que gravaria em
`.plumb/pending-brain.jsonl`.
