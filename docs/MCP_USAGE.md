# Uso das ferramentas MCP

Guia por tarefa. As instruções que o servidor envia ao agente são o resumo disto; aqui ficam
os exemplos completos.

## Começar num projeto

O hook de início de sessão do Plumb injeta o pacote de contexto. Sem hook:

```python
context_get(project=".")                                   # projeto inteiro
context_get(project=".", paths=["src/payments/Charge.java"])  # + regras com escopo
context_get(project=".", query="estorno")                  # + itens relacionados
```

Projeto não ligado: `context_get` diz como ligar. Ligue uma vez:

```python
project_link(project=".")   # domain = repo; workspace = o de outro repo do mesmo dono
```

Com `paths` ou `query`, o que casa vem **em foco**, com o começo do `content` (sem `item_get`
depois), e o retorno traz `sensitive: true` se os arquivos tocam uma área marcada com a keyword
`sensivel` — o Plumb usa isso para pedir revisão de segurança. Os itens em foco contam como uso.

Workspace = contexto de trabalho (empresa, cliente, `Pessoal`); domain = repositório. O pacote
junta o domain do repositório, o `Geral` do mesmo workspace (convenções que valem para os repos
daquele contexto) e `Global/Geral` (o que vale para você em qualquer lugar). Um repositório não vê
o domain de outro. Sem workspace, o `project_link` usa o de outro repo do mesmo dono já ligado;
no primeiro repo de um dono, o nome do dono no remote (sem remote, `Pessoal`).

## Procurar e ler

```python
item_search(query="migração flyway", project=".", limit=5)      # resumos
item_get(keys=["proc/migration", "regra/money"], project=".")   # completos
item_get(ids=["9b2c..."])
```

- Sem `project` nem `workspace`, busca no projeto da pasta atual (se ligado); `everywhere=True` busca em toda a base. Cada resultado traz `uses` (vezes que o item foi devolvido de propósito).
- A busca ignora acento e plural e começa pela relevância. Busca vazia não prova ausência:
  tente um sinônimo (e grave o sinônimo em `keywords` quando achar).

## Gravar

Uma ferramenta, em lote e numa transação. O modo vem de cada entrada:

| Entrada traz | Faz |
|---|---|
| `key` | upsert no domain (cria ou atualiza; não duplica) — **o preferido** |
| `id` | atualiza o item |
| nenhum dos dois | cria e devolve `similar` (títulos parecidos já guardados) |

```python
item_save(project=".", items=[
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

### Planos de mudança (`task`)

O Plumb guarda o plano de cada mudança como item `task` (`key: "mudanca/<id>"`): o `summary`
é o andamento em uma linha ("Construindo: falta recusar método inválido"), o `content` é o plano.
Enquanto `status` é `active`, ele aparece em "Mudanças em andamento" no pacote do início da
sessão; ao concluir, `status: "done"` — sai do pacote e continua na busca, como histórico.

```python
item_save(project=".", items=[{"key": "mudanca/pay-142", "summary": "Construindo: 1 de 2 feitos"}])
item_save(project=".", items=[{"key": "mudanca/pay-142", "status": "done",
                               "summary": "Concluída: Pix devolve o QR code"}])
```

### Promover, renovar, aposentar

```python
item_save(items=[{"id": "...", "memory_class": "longterm"}])   # só sobe; peça o "sim"
item_save(items=[{"id": "...", "ttl_days": 30}])               # renova um ephemeral
item_save(items=[{"id": "...", "status": "deprecated"}])        # sai da busca, fica o histórico
```

### Substituir

```python
item_save(project=".", items=[{"key": "proc/deploy-ci", "type": "procedure", ...,
  "relations": [{"type": "supersedes", "target": "proc/deploy"}]}])
```

O alvo vira `superseded` e sai da busca e do contexto. Tipos de relação: `related_to`,
`depends_on`, `implements`, `references`, `supersedes`, `derived_from`. `target` é id ou key
do mesmo domain, inclusive de um item criado no mesmo lote.

### Erros

- Um erro desfaz o lote inteiro e aponta a entrada (`Entrada 1 (regra/x): ...`).
- Segredos são recusados sem eco do valor em itens comuns: grave um item `secret` sem valor.

### Segredos

```python
item_save(project=".", items=[{"key": "segredo/npm-token", "type": "secret",
  "title": "Token do npm", "summary": "Publicar pacotes no npm"}])
# → [{..., "has_value": false, "fill_url": "http://127.0.0.1:8765/ui/#/c/default/w/.../i/..."}]
```

Passe o `fill_url` ao usuário: ele preenche o valor na UI local. Nunca peça o valor no chat
(`value`/`valor` no `item_save` é recusado). O pacote de contexto lista os segredos com o estado
e, quando há valor, como usar:

```bash
knowledge-mcp run --env NPM_TOKEN=segredo/npm-token -- npm publish
knowledge-mcp run --stdin segredo/registry -- docker login -u ci --password-stdin registry.x
```

Sem valor, o `run` não roda o comando e devolve o link para preencher.

## Administração (perfil `all`)

```python
structure_list()                                    # árvore com contagens
structure_delete(workspace="Teste")                 # preview do que seria apagado
structure_delete(workspace="Teste", confirm=True)   # só depois do "sim" do usuário
item_delete(item_id="...")                          # prefira status=deprecated
relation_delete(relation_id="...")                  # id vem em item_get → relations
vocabulary(kind="tags")                             # reaproveite antes de criar variações
vocabulary(kind="labels", action="create", name="lgpd")
backup_export(workspace="agenda-api")                # ZIP em <home>/exports
backup_import(file_path="...zip")                   # workspace novo, ids novos
artifact_attach(item_id="...", file_path="C:/docs/arquitetura.png")
artifact_get(artifact_id="...")                     # base64; confira file_size antes
```

## Conexões com outros bancos

Pela UI (`knowledge-mcp ui`): cadastrar Postgres/MySQL, testar, sincronizar schema e migrar
workspaces. As conexões ficam em `<home>/connections.json`; as ferramentas do cérebro e de
administração aceitam `connection_id` opcional (sem ele, o catálogo `default`); só
`health_check` não aceita e verifica sempre o catálogo `default`. Senhas nunca passam pela conversa.

## Problemas comuns

| Sintoma | Ação |
|---|---|
| "Projeto não ligado" | `project_link` ou `/plumb-setup` |
| Busca não acha | sinônimo; `include_inactive=True` se pode ter sido substituído |
| `Entrada N (...)` | corrija a entrada N; nada do lote foi gravado |
| "parece conter um segredo" | tire o valor; crie um item `secret` sem valor e passe o `fill_url` ao usuário |
| Servidor fora do ar | o Plumb segue com aviso e guarda em `~/.knowledge-os/pending.jsonl` (uma entrada de `item_save` por linha, com `project`); o hook da próxima sessão grava, ou `knowledge-mcp pending` |
| Banco remoto inacessível | `health_check`; a UI testa a conexão |
