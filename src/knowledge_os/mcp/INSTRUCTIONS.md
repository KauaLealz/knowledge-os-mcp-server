# Segundo cérebro (Knowledge OS)

Memória durável: o que seguir, como fazer, o contexto do projeto e o trabalho (planos e o
porquê). Schema mínimo: a nuance e o ciclo vivem em **tags**, não em campos.

**Onde mora (= onde vale):** workspace = contexto (empresa, cliente, Pessoal); project =
repositório/sistema; subject = conceito dentro do project (opcional). O item pode morar em
**qualquer nível** e vale onde mora **e abaixo**: no workspace vale em todos os projects dele;
no project, só nele; no subject, só nele. Não há `scope` — o alcance é a hierarquia.

**Conexão:** os dados são arquivos Markdown numa pasta git. Sem conexão nada funciona:
`connection_create(name, path[, remote_url])`; `connection_list`, `connection_delete` (não
apaga a pasta). `health_check()` mostra as conexões e os arquivos que não leram.

**Ler:** o pacote do projeto vem injetado no início da sessão. Dúvida:
`item_search(query, repo=".")` (até 5 de uma vez com `queries=[...]`; `paths=[arquivos]` sobe
as regras daqueles arquivos), depois `item_get(keys=[...], repo=".")`; ligações:
`item_graph(keys=[...], repo=".")`. Usou um item e ele estava errado ou velho? **Corrija ou
remova** (é git, dá para voltar) — não há feedback.

**Quando gravar** (`item_save(items=[...], repo=".")`, em lote, `key` estável — regrava sem
duplicar): o usuário enuncia uma regra ou preferência (grave na hora); você destrava algo não
óbvio (`howto`); ao fechar uma mudança, o que durar (uma `rule`, um `howto`, o `work` com o
porquê). A nuance vai em **tags** (`decision`, `troubleshoot`, `security`…); o ciclo do `work`
em tags (`draft`, `active`, `done`, `archived`). Antes de criar, `item_search`. Não é item:
bug, medição datada, id de tarefa. `summary` de 1–2 frases com o porquê.

**Quando confirmar:** o que você inferiu (não foi dito pelo usuário) — mostre e espere o "sim".
Destrutivos (`item_delete`, `*_delete`, `tag_delete`) devolvem prévia sem `confirm`; só passe
`confirm=True` com pedido explícito. Tudo é commit no git da conexão: dá para voltar.

**Links:** um item liga a outro item (`relation_create`, `depends_on`/`relates_to`) ou a uma
referência externa (`{url}` ou `{path}` em `links`). Toda resposta de item traz `url` (link da
UI local); cole-o ao usuário ao criar um `work` e na entrega. Tags: vocabulário curto e
reaproveitado — `tag_list` antes de criar; 1 a 3 de área/tema.

**Segredos:** item `secret` (`secret/<nome>`) sem valor; passe ao usuário o `fill_url` da
resposta (ele preenche na UI local). Nunca peça nem grave o valor no chat. Usar:
`knowledge-mcp run --env VAR=secret/<nome> -- <comando>`.

**Sem ligação:** `repo(action="link", repo=".")` (ou `/plumb-setup`). **Fora do ar:** siga,
avise e guarde a entrada do `item_save` em `~/.knowledge-os/pending.jsonl`.

**Organização:** `workspace_*`, `project_*`, `subject_*` (list, create, update, merge,
delete), `repo` (link, list, unlink, sync), `tag_list`/`tag_create`/`tag_update`/`tag_delete`,
`relation_create`/`relation_delete`.

## Taxonomia

| Tipo | Guarda |
|---|---|
| `rule` | o que deve ser seguido + o porquê (convenção, decisão, regra de negócio) |
| `howto` | passos repetíveis ou diagnóstico (sintoma/causa/solução) |
| `context` | pano de fundo: produto, mapa, stack, glossário, ambiente |
| `work` | o trabalho: plano/spec + decisões (o porquê durável); ciclo por tag |
| `secret` | referência a um segredo (sem o valor) |

| Campo | Valores |
|---|---|
| tags de ciclo | `draft`, `active`, `done`, `archived` |
| tags de nuance (base, extensível) | `decision`, `troubleshoot`, `security`, `pattern`, `map`, `glossary`, `product`, `environment`, `business`, `process` |
| link item→item (`rel`) | `depends_on`, `relates_to` |

Key: `<tipo>/<nome>` (nome em minúsculas com `-`); fora do padrão grava com aviso, e a key de um item existente nunca muda.

Alcance: o item vale onde mora na hierarquia (workspace → project → subject) e abaixo. Não há `scope`, `status`, `subtype`, `origin` nem expiração — a nuance e o ciclo vão em `tags`.

`links` (unificado): `{item, rel}` liga a outro item; `{url[, title]}` a uma URL; `{path}` a um arquivo/glob do repositório.
