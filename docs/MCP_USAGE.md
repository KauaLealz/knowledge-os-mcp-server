# Uso das ferramentas MCP

Guia por tarefa. As instruções que o servidor envia ao agente são o resumo disto; aqui ficam
os exemplos completos.

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

A primeira conexão vira a padrão (a usada sem `connection_id`); troque a padrão pela UI.

## Começar num projeto

O hook de início de sessão do Plumb injeta o pacote de contexto. Sem hook:

```python
context_get(repo=".")                                   # projeto inteiro
context_get(repo=".", paths=["src/payments/Charge.java"])  # + regras com escopo
context_get(repo=".", query="estorno")                  # + itens relacionados
```

Projeto não ligado: `context_get` diz como ligar. Ligue uma vez:

```python
repo(action="link", repo=".")   # project = repo; workspace = o de outro repo do mesmo dono
```

Com `paths` ou `query`, o que casa vem **em foco**, com o começo do `content` (sem `item_get`
depois), e o retorno traz `sensitive: true` se os arquivos tocam uma área marcada com a keyword
`sensivel` — o Plumb usa isso para pedir revisão de segurança. Os itens em foco contam como uso.

Workspace = contexto de trabalho (empresa, cliente, `Pessoal`); project = repositório. O pacote
junta o project do repositório, o `Geral` do mesmo workspace (convenções que valem para os repos
daquele contexto) e `Global/Geral` (o que vale para você em qualquer lugar). Um repositório não vê
o project de outro. Sem workspace, o `repo(action="link")` usa o de outro repo do mesmo dono já
ligado; no primeiro repo de um dono, o nome do dono no remote (sem remote, `Pessoal`).

## Procurar e ler

```python
item_search(query="migração flyway", repo=".", limit=5)         # resumos
item_search(query="estorno", repo=".", subject="pagamentos")    # restrito a um subject do project
item_get(keys=["proc/migration", "regra/money"], repo=".")      # completos
item_get(ids=["9b2c..."])
```

- Sem `repo` nem `workspace`, busca no projeto da pasta atual (se ligado); `everywhere=True` busca em toda a base. Cada resultado traz `uses` (vezes que o item foi devolvido de propósito).
- `subject` filtra pelo assunto (nome ou id) dentro do project resolvido — exige que um project tenha sido resolvido (por `repo` ou por `workspace`+`project`).
- A busca ignora acento e plural e começa pela relevância. Busca vazia não prova ausência:
  tente um sinônimo (e grave o sinônimo em `keywords` quando achar).

## Gravar

Uma ferramenta, em lote e numa publicação só (um commit). O modo vem de cada entrada:

| Entrada traz | Faz |
|---|---|
| `key` | upsert no project (cria ou atualiza; não duplica) — **o preferido** |
| `id` | atualiza o item |
| `id` + `workspace`/`project`/`subject` novos | *move* o item para esse workspace/project/subject (ver abaixo) |
| nenhum dos dois | cria e devolve `similar` (títulos parecidos já guardados) |

```python
item_save(repo=".", items=[
  {"key": "regra/money", "type": "rule",
   "title": "Money em pagamentos", "summary": "Valores sempre em Money, nunca double",
   "content": "...", "scope_paths": ["src/payments/**"], "source": "PAY-142",
   "keywords": "dinheiro centavos BigDecimal"},
  {"key": "decisao/pix-vencido", "type": "insight",
   "title": "Pix vencido é recusado", "summary": "Recusar, sem estorno automático",
   "content": "Porque o financeiro revisa caso a caso.", "source": "PAY-142"},
])
```

Convenção de keys: `regra/...`, `decisao/...`, `proc/...`, `padrao/...`, `gotcha/...`,
`contexto/...` — minúsculas, números, `.` `_` `/` `-`.

### Mover um item

Uma entrada com `id` e também `workspace`+`project` move o item para esse workspace/project
(criados se não existirem); o `subject`, se vier junto, é resolvido ou criado no project novo —
sem `subject`, o item fica sem assunto. Uma entrada com `id` e só `subject` (sem
workspace/project) move o item para esse subject dentro do project atual, sem trocar de
workspace/project. Em qualquer caso, `id`, `created_at`, tags, labels e relations do item não
mudam — só a localização (e o caminho do arquivo).

```python
item_save(items=[{"id": "9b2c...", "workspace": "Polara", "project": "projpro",
                   "subject": "pagamentos"}])   # move para outro workspace/project/subject
item_save(items=[{"id": "9b2c...", "subject": "estorno"}])   # só troca o subject, mesmo project
```

### Promover, renovar, aposentar

```python
item_save(items=[{"id": "...", "memory_class": "longterm"}])   # só sobe; peça o "sim"
item_save(items=[{"id": "...", "ttl_days": 30}])               # renova um ephemeral
item_save(items=[{"id": "...", "status": "deprecated"}])        # sai da busca, fica o histórico
```

### Substituir

```python
item_save(repo=".", items=[{"key": "proc/deploy-ci", "type": "procedure", ...,
  "relations": [{"type": "supersedes", "target": "proc/deploy"}]}])
```

O alvo vira `superseded` e sai da busca e do contexto. Tipos de relação: `related_to`,
`depends_on`, `implements`, `references`, `supersedes`, `derived_from`. `target` é id ou key
do mesmo project, inclusive de um item criado no mesmo lote.

### Publicação (repositório git da conexão)

Todo item não secreto é um arquivo Markdown na pasta da conexão e cada gravação é publicada
nesse repositório, conforme o `review_mode` da conexão:

- `direct` (padrão): `item_save` escreve, comita (e empurra, se há `remote_url`) na mesma
  chamada — o retorno é o de sempre, `{index, id, key, action, ...}`.
- `pr`: a mesma gravação vai para uma branch nova e abre um Pull Request (ou uma Issue, se o
  token não tem permissão de push); cada entrada do lote devolve `{status: "pending_review",
  pr_url}` (ou `{status: "issue_opened", issue_url}`) em vez do resultado de sempre. A mudança
  só aparece depois que o PR for mergeado e alguém rodar `repo(action="sync")` (ou o hook de
  início de sessão sincronizar).

`item_delete`, `relation_create` e `relation_delete` seguem a mesma regra: em modo `pr`, a
mudança também fica pendente de revisão.

### Erros

- Um erro desfaz o lote inteiro e aponta a entrada (`Entrada 1 (regra/x): ...`).
- Segredos são recusados sem eco do valor em itens comuns: grave um item `secret` sem valor.

### Segredos

```python
item_save(repo=".", items=[{"key": "segredo/npm-token", "type": "secret",
  "title": "Token do npm", "summary": "Publicar pacotes no npm"}])
# → [{..., "has_value": false, "fill_url": "http://127.0.0.1:8765/ui/#/c/<conexão>/w/.../i/..."}]
```

Passe o `fill_url` ao usuário: ele preenche o valor na UI local. Nunca peça o valor no chat
(`value`/`valor` no `item_save` é recusado). O pacote de contexto lista os segredos com o estado
e, quando há valor, como usar:

```bash
knowledge-mcp run --env NPM_TOKEN=segredo/npm-token -- npm publish
knowledge-mcp run --stdin segredo/registry -- docker login -u ci --password-stdin registry.x
```

Sem valor, o `run` não roda o comando e devolve o link para preencher.

## Organizar e administrar

```python
workspace_list()                                          # workspaces com contagens
workspace_create(name="Polara")
workspace_rename(name="polara", new_name="Polara")
workspace_merge(source="Polara Antiga", target="Polara")
workspace_delete(name="Teste", confirm=True)               # sem confirm, só preview

project_list(workspace="Polara")
project_create(workspace="Polara", name="projpro")
project_rename(workspace="Polara", name="projpro-old", new_name="projpro")
project_merge(workspace="Polara", source="projpro-old", target="projpro")

subject_list(workspace="Polara", project="projpro")
subject_create(workspace="Polara", project="projpro", name="pagamentos")

repo(action="list", workspace="Polara")                    # auditar o que está ligado
repo(action="unlink", repo="github.com/org/antigo")
repo(action="sync")                       # puxa o que mudou no remote da conexão

item_delete(item_id="...")                          # prefira status=deprecated
relation_create(source_item_id="...", target_item_id="...", relation_type="depends_on")
relation_delete(relation_id="...")                  # id vem em item_get → relations
tag_list()                                          # reaproveite antes de criar variações
label_create(name="lgpd")
```

Toda ferramenta do cérebro e de administração aceita `connection_id` opcional (sem ele, a
conexão padrão). Tudo o que muda vira commit no repositório da conexão: para voltar atrás ou
levar para outra máquina, use o git (histórico, push, clone).

## Conexões (repositórios git)

Criar é só pelo MCP (`connection_create`, acima). A UI (`knowledge-mcp ui`) lista as conexões
com o caminho da pasta, o remote, o modo e o estado (pasta existe / é repositório git), e edita
nome, `remote_url`, `review_mode` (`direct` ou `pr`) e se está ativa; testa o remote
(`git ls-remote`, sem clonar), define a padrão e apaga (só do cadastro). As conexões ficam em
`<home>/connections.json`; `health_check` verifica a conexão padrão.

Sem `remote_url`, a conexão é um repositório git só local (sem GitHub) — útil para manter
conhecimento fora de qualquer remote. Com `remote_url`, a criação clona; dali em diante,
`item_save`/`item_delete`/`relation_delete` publicam conforme o `review_mode`, e
`repo(action="sync")` (ou o hook de início de sessão) puxa o que mudou de fora.

## Problemas comuns

| Sintoma | Ação |
|---|---|
| "Projeto não ligado" | `repo(action="link")` ou `/plumb-setup` |
| Busca não acha | sinônimo; `include_inactive=True` se pode ter sido substituído |
| `Entrada N (...)` | corrija a entrada N; nada do lote foi gravado |
| "parece conter um segredo" | tire o valor; crie um item `secret` sem valor e passe o `fill_url` ao usuário |
| Servidor fora do ar | o Plumb segue com aviso e guarda em `~/.knowledge-os/pending.jsonl` (uma entrada de `item_save` por linha, com `repo`); o hook da próxima sessão grava, ou `knowledge-mcp pending` |
| "Nenhuma conexão configurada" | crie uma com `connection_create(name, path)` |
| Remote git inacessível | `health_check`; a UI testa a conexão (`git ls-remote`) |
| PR aberto não aparece na busca | normal em `review_mode="pr"`: a mudança só aparece depois do PR mergeado e `repo(action="sync")` |
