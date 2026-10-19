# Uso das ferramentas MCP

Guia por tarefa. As instruções que o servidor envia ao agente são o resumo disto; aqui ficam
os exemplos completos. São 31 ferramentas; todas aceitam `connection_id` opcional (a conexão
padrão é a usada sem ele), menos `connection_*` e `health_check`. Voltar ao
[README](../README.md).

Vocabulário: o **workspace** é o contexto (empresa, cliente, Pessoal), o **project** é um
repositório e o **subject** é um conceito opcional dentro do project. O item **mora** num nível
da hierarquia (workspace, project ou subject) e **vale onde mora e abaixo** — não há campo de
alcance: um item no workspace vale em todos os projects dele; no project, só nele.

Cinco tipos, sem subtipo: `rule`, `howto`, `context`, `work` e `secret`. A nuance e o ciclo vão
em **tags**: ciclo `draft`/`active`/`done`/`archived`; nuance `decision`/`troubleshoot`/
`security`/`pattern`/`map`/`glossary`/`product`/`environment`/`business`/`process` (base,
extensível).

Uma regra vale para todas as chamadas: erro de validação sempre diz como corrigir (lista dos
valores válidos, a chamada certa).

## Primeiro: uma conexão

Os dados ficam numa pasta (repositório git) — a conexão. Sem nenhuma, toda ferramenta responde
"Nenhuma conexão configurada. Crie uma com connection_create(name, path[, remote_url])." Crie
pelo MCP (a UI e a API não criam):

```python
connection_create(name="pessoal", path="C:\\caminho\\da\\pasta")   # pasta comum vira repo git
connection_create(name="empresa", path="/home/eu/empresa-knowledge",
                  remote_url="git@github.com:org/knowledge.git", review_mode="pr")
connection_list()
connection_delete(id="...")       # tira do cadastro; a pasta e os arquivos ficam
```

A primeira conexão vira a padrão; troque a padrão pela UI.

## Começar num projeto

O hook de início de sessão do Plumb injeta o pacote de contexto do projeto. Sem hook, ou para
ir além dele, use a busca:

```python
item_search(repo=".")    # sem consulta: o essencial do projeto, em grupos
```

A resposta traz `{groups: [{group, results}]}` com `seguranca` (itens com a tag `security`),
`regras`, `contexto` e `trabalho` (os `work` ativos). Cada resultado é um resumo: `id`, `key`,
`type`, `title`, `summary`, `tags`, `where`, `score`, `matched_in` e `snippet`.

Projeto não ligado: a resposta traz só os itens globais e uma `suggestion` com a chamada que
liga. Ligue uma vez:

```python
repo(action="link", repo=".")   # project = repo; workspace = o de outro repo do mesmo dono
repo(action="list", workspace="Polara")
repo(action="unlink", repo="github.com/org/antigo")
repo(action="sync")             # puxa o que mudou no remote da conexão
```

Se a resposta trouxer `candidate_match`, o nome novo se parece com um existente: repita com o nome
exato do existente, ou passe `confirm_new=True` se for mesmo novo.

## Buscar

```python
item_search(query="migração flyway", repo=".")
item_search(queries=["estorno", "pix"], repo=".", paths=["src/payments/Charge.java"])
item_search(query="deploy", repo=".", types=["howto"], tags=["procedure"])
item_search(query="lgpd", workspace="Polara")      # o workspace inteiro
item_search(query="token", everywhere=True)        # tudo, sem distância
```

- **`paths`** = os arquivos em que você vai mexer: sobe as regras com um link `{path}` que casa, e
  cada resultado traz `excerpt` (até 600 caracteres do `content`), em geral sem precisar de
  `item_get`.
- **`queries`**: até 5 consultas numa chamada, com o resultado em `groups` por consulta. Seis é
  erro ("no máximo 5").
- **Filtros:** `types`, `tags` (todas precisam bater) e `limit` (1–100).
- **Alcance pela hierarquia:** quanto mais perto do project do repositório, maior o peso; `where`
  diz onde o item mora. `workspace=` amplia para o workspace inteiro; `everywhere=True`, para tudo.
- **Padrão:** esconde os itens com a tag `archived`.
- A busca entende identificadores: `saveBatch`, `save_batch` e `ItemService.save` se acham pelas
  partes, e um código como `ERR_CONN_42` é achado como está.

Depois da busca, abra o que importa:

```python
item_get(keys=["rule/money", "howto/deploy"], repo=".")
item_get(ids=["3f2a..."])
item_get(keys=["rule/money"], workspace="Polara", project="app")
```

Até 20 por chamada. Key que não se resolve volta `{key, missing: true}`; sem `repo`, só os globais
se resolvem pela key (passe `repo="."`, ou `workspace` e `project`, ou o `id`).

## Gravar em lote

`item_save` grava até 20 itens numa publicação só; um erro desfaz o lote e aponta a entrada.

```python
item_save(repo=".", items=[
  {"key": "rule/money", "type": "rule",
   "title": "Money em pagamentos",
   "summary": "Valores em Money, nunca double: arredondamento quebra a conciliação",
   "content": "...", "tags": ["pagamentos", "code"], "links": [{"path": "src/payments/**"}]},
  {"key": "howto/deploy", "type": "howto",
   "title": "Deploy em produção", "summary": "passos e verificação do deploy",
   "content": "1. ...", "tags": ["deploy", "procedure"]},
])
```

- Por entrada: `key` → upsert no project (o preferido: regrava sem duplicar); `id` → atualiza só
  os campos informados (com `workspace` e `project` novos, move o item); sem os dois → cria e
  devolve `similar` (títulos parecidos: confira antes de duplicar).
- A resposta é uma linha por entrada: `{index, id, key, action, warnings, similar?}` com
  `action` = `created`, `updated` ou `unchanged`.
- A nuance e o ciclo vão em `tags` (ex.: `decision`, `troubleshoot`, `security`, `draft`,
  `active`, `done`, `archived`). `links` liga a outro item (`{item, rel}`) ou a uma referência
  externa (`{url}` | `{path}`).
- `warnings` avisa, sem recusar: a key fora do padrão `<tipo>/<nome>` e a tag nova (com sugestão
  de uma parecida).
- Arquivar: `item_save(repo=".", items=[{"key": "rule/x", "tags": ["archived"]}])`.
- Limites e erros: no máximo 20 entradas por chamada; key com espaço (ou outro caractere fora de
  letras, números, `.`, `_`, `-` e `/`) é **erro de gravação**, não aviso.
- Conteúdo com cara de segredo (chave de nuvem, token, `password=...`) é recusado.

## Relacionar e ver o grafo

```python
relation_create(repo=".", items=[
  {"source": "howto/deploy-ci", "type": "depends_on", "target": "rule/deploy"},
  {"source": "rule/money", "type": "relates_to", "target": "context/pagamentos"},
])
relation_delete(repo=".", items=[{"source": "rule/a", "type": "relates_to", "target": "rule/b"}])

item_graph(keys=["rule/money"], repo=".")                          # vizinhos diretos
item_graph(keys=["rule/money"], repo=".", depth=2, relation_types=["depends_on"],
           direction="out")
```

Tipos de link item↔item: `depends_on` e `relates_to` (sem `supersedes`: o item anterior é
ajustado ou removido). Source e target vão por key ou id (até 20 entradas, atômico); repetir uma
ligação é no-op (`unchanged`). Os links item↔item ficam no campo `links` do item de origem.

`item_graph` aceita até 5 keys, `depth` de 1 a 3, `limit` até 100 e `direction` `both`, `out` ou
`in`, e enxerga só o que o repositório alcança. Devolve `{nodes, edges, truncated, total_by_hop}`;
as keys pedidas vêm com `hop: 0`. Ao passar de `limit`, `truncated` fica `true` e
`total_by_hop` traz o total real por salto.

## Tags

```python
tag_list()                                       # [{name, count}], inclui as com count 0
tag_create(names=["lgpd", "pix"])
tag_update(name="pix", new_name="pagamento-pix")  # renomeia em todos os itens; se já existe, mescla
tag_delete(names=["lgpd"])                        # prévia, com o número de itens afetados
tag_delete(names=["lgpd"], confirm=True)          # remove dos itens e do vocabulário
```

Nomes em kebab-case minúsculo. Uma tag nova num `item_save` é criada, com aviso e a sugestão de
uma existente parecida.

## Item errado ou velho

Não há feedback: ao usar um item que estava errado ou desatualizado, **corrija-o** (regrave pela
mesma `key`) ou **remova-o** (`item_delete`). Tudo é commit no git da conexão: dá para voltar.

## Limpeza com prévia

`item_delete` trabalha em três passos e nunca apaga sem `confirm=True`:

```python
item_delete(repo=".")                                  # 1. candidatos: [{key, id, reason}]
item_delete(keys=["rule/velha"], repo=".")             # 2. prévia do que sairia
item_delete(keys=["rule/velha"], repo=".", confirm=True)   # 3. remove (e as relações que o apontavam)
```

`reason` é `archived` (tag `archived` há muito tempo) ou `unused` (nunca aberto há muito tempo).
Mostre a prévia ao usuário antes de passar `confirm=True`. Para aposentar mantendo o item,
prefira a tag `archived` no `item_save`. Tudo é commit no git da conexão: dá para voltar.

## Segredos

Token, senha e chave são itens `secret`, sem valor:

```python
item_save(repo=".", items=[{"key": "secret/npm-token", "type": "secret",
          "title": "Token do npm", "summary": "publicar no npm"}])
```

A resposta traz `has_value: false` e `fill_url`: passe o link ao usuário, que preenche o valor na
UI local. **Nunca** peça nem grave o valor no chat; `item_save` recusa campo de valor. Para usar:

```bash
knowledge-mcp run --env NPM_TOKEN=secret/npm-token -- npm publish
```

O valor vai só para o processo filho e a saída volta redigida. Detalhes e modelo de ameaça no
[README](../README.md#segredos).

## Organização (hierarquia)

```python
workspace_create(name="Polara", description="cliente")
workspace_list()
workspace_update(name="Polara", description="cliente estratégico")
workspace_merge(source="polara-antiga", target="Polara")
workspace_delete(name="Teste")                         # prévia; com confirm=True apaga

project_create(workspace="Polara", name="Geral")
project_list(workspace="Polara")                       # cada project traz os seus subjects
project_update(workspace="Polara", name="app", new_name="app-web")
project_merge(workspace="Polara", source="app-old", target="app")
project_delete(workspace="Polara", name="Teste", confirm=True)

subject_create(workspace="Polara", project="app", name="pagamentos")
subject_list(workspace="Polara", project="app")
subject_update(workspace="Polara", project="app", name="pagto", new_name="pagamentos")
subject_merge(workspace="Polara", project="app", source="pagto", target="pagamentos")
subject_delete(workspace="Polara", project="app", name="pagamentos", confirm=True)
```

- `create` e `update` aceitam `description`; `update` aceita também `new_name`.
- O **alcance vem de onde o item mora**, não de um campo: um item no nível do workspace vale em
  todos os projects dele (é o jeito de ter regras transversais); no project, só nele; no subject,
  só nele.
- `merge` e `delete` são destrutivos: o `delete` devolve uma prévia sem `confirm`; só passe
  `confirm=True` com pedido explícito do usuário.
- **O alcance não é fronteira de segurança:** controla o que a busca e o pacote mostram;
  `item_get(ids=[...])` e `everywhere=True` leem a conexão inteira. Um `secret` vale pelo mesmo
  alcance: para usá-lo fora do seu project, guarde-o num nível mais alto da hierarquia.

## Conexões e saúde

```python
connection_list()     # id, name, path, remote_url, review_mode, enabled, is_default
health_check()        # {status, version, connections: [{name, path, ok, parse_errors}], gh_authenticated}
```

`parse_errors` lista os arquivos `.md` com frontmatter inválido ou id duplicado: eles ficam de
fora até serem corrigidos. Com `review_mode="pr"`, as gravações voltam
`{status: "pending_review", pr_url}` (ou `issue_opened`/`issue_url`) em vez do resultado de
sempre, e a mudança só aparece depois do merge e de um `repo(action="sync")`.

## Fora do ar

Se o servidor não responder, siga o trabalho e guarde a entrada que iria no `item_save` na fila
offline: `knowledge-mcp pending --repo .` (grava em `~/.knowledge-os/pending.jsonl`).
