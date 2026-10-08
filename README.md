# Knowledge OS — segundo cérebro para agentes

Servidor MCP local que guarda o conhecimento durável do seu trabalho — regras, decisões e o
porquê, como fazer, contexto e specs — e o devolve aos agentes com pouco custo de contexto. É a
memória obrigatória do [Plumb](https://github.com/KauaLealz/plumb-harness): o hook de início de
sessão injeta o pacote do projeto e o fechamento de cada mudança grava o que valeu, numa chamada.

- **Só arquivos, num repositório git seu:** cada conexão é uma pasta (repositório git) que você
  escolhe; cada item é um arquivo Markdown com frontmatter YAML, e cada escrita é um commit. O
  que está na pasta é a verdade; não há banco nem índice para reconstruir.
- **Alcance explícito (`scope`):** cada item diz onde vale — só no project, no workspace inteiro
  ou em qualquer lugar — e a busca, o pacote e o grafo respeitam isso.
- **Busca explicada, sem embeddings, que acerta em PT-BR:** em memória, sem acento, por radical e
  prefixo, entende identificadores (`ItemService.saveBatch` acha "service" e "batch") e diz por
  que cada resultado veio (`matched_in`, `snippet`, `where`).
- **Escrita em lote e idempotente:** `item_save` grava até 20 itens numa publicação; a `key`
  estável regrava sem duplicar.
- **Aprende com o uso:** `item_feedback` registra o que ajudou, o que não serviu e o que está
  velho; o ranking e o relatório de revisão usam isso.
- **Segredos sem passar pelo modelo:** o agente cria o segredo vazio, você preenche na UI local e
  ele é usado por `knowledge-mcp run`, que entrega o valor só ao processo filho.
- **Seguro:** recusa segredos em itens comuns; operações destrutivas pedem confirmação e mostram
  uma prévia antes.

## Como começar

1. **Instalar**

   ```bash
   uv tool install "git+https://github.com/KauaLealz/knowledge-os-mcp-server"      # comando `knowledge-mcp`
   knowledge-mcp --version
   ```

   Para desenvolver, clone e instale editável: `uv tool install --editable <pasta-do-clone>`.

2. **Registrar no cliente MCP.** O instalador do Plumb (`npx plumb-harness install`) registra o
   servidor no Claude Code e no Cursor, com o hook de início de sessão. À mão:

   ```bash
   claude mcp add --scope user knowledge-os -e LOG_LEVEL=WARNING -- knowledge-mcp
   ```

   ```json
   // ~/.cursor/mcp.json
   { "mcpServers": { "knowledge-os": { "command": "knowledge-mcp",
     "env": { "LOG_LEVEL": "WARNING" } } } }
   ```

3. **Criar a primeira conexão, pelo MCP.** Nada é criado sozinho: até existir uma conexão, toda
   operação responde "Nenhuma conexão configurada. Crie uma com connection_create(name, path[,
   remote_url])." Peça ao agente (ou chame a ferramenta):

   ```
   connection_create(name="pessoal", path="C:\\caminho\\da\\pasta")
   connection_create(name="empresa", path="/home/eu/empresa-knowledge", remote_url="git@github.com:org/knowledge.git")
   ```

   `path` é uma pasta absoluta: se já for um repositório git, é usada como está; senão vira um
   (`git init`, preservando o que já tiver dentro). Com `remote_url`, a pasta é o destino do
   clone e cada escrita é empurrada para lá. A primeira conexão vira a padrão. A UI
   (`knowledge-mcp ui`) lista, edita, testa, define a padrão e apaga conexões, mas não cria.

4. **Ligar o repositório do projeto.** Dentro do repositório em que você trabalha, rode
   `/plumb-setup` (no Plumb) ou `knowledge-mcp link --repo .` — ou peça ao agente
   `repo(action="link", repo=".")`. O project é o repositório; o workspace, o do dono do remote.

Se a pasta já tem arquivos de uma versão anterior do Knowledge OS, nada precisa ser migrado: a
leitura traduz o formato antigo e a próxima gravação de cada item já sai no formato atual.

## Onde ficam os dados

- **Na pasta de cada conexão** (o repositório git que você escolheu): todos os itens, como
  `<workspace>/<project>/<key>.md`, os `.knowledge.yaml` (descrição e `scope` de workspaces,
  projects e subjects, e o vocabulário de tags) e os valores de segredos cifrados em `.secrets/`
  (fora do git: nunca entram nele).
- **No home** (`KNOWLEDGE_OS_HOME`, padrão `~/.knowledge-os`), só estado desta máquina:
  `connections.json` (as conexões e a padrão), `repos.json` (repositório local → conexão,
  workspace e project), `usage/<conexão>.json` (contadores de uso por item),
  `searches/<conexão>.jsonl` (buscas que voltaram vazias), `locks/` (travas de escrita entre
  processos) e a fila offline `pending.jsonl`. Nenhum item fica aí.

Fazer backup ou levar para outra máquina é o mesmo que com qualquer repositório git: commit,
push, clone.

## Modelo

```
Workspace = contexto de trabalho     ex.: Polara (empresa), Pessoal
 └── Project = um repositório          ex.: app, synapse
      └── Subject (opcional)           agrupador de assunto dentro do project, ex.: pagamentos
           └── Item: type · subtype · key · title · summary · content · scope · scope_paths ...
```

O item **mora** no project em que foi salvo; **onde vale** é o `scope`. Cinco tipos, cada um
com subtipos opcionais; status, scope, origin, relações e feedback são conjuntos fechados (a
taxonomia abaixo é a mesma que o servidor envia ao agente nas instruções):

| Tipo | Subtipos (opcionais) |
|---|---|
| `rule` | `code`, `pattern`, `security`, `business`, `process`, `decision` |
| `howto` | `procedure`, `troubleshoot` |
| `context` | `product`, `map`, `stack`, `glossary`, `environment` |
| `spec` | `change`, `setup`, `dream` |
| `secret` | — |

| Campo | Valores |
|---|---|
| status | `active`, `review`, `archived`; só `spec`: `draft`, `done` (`expired` é derivado do ttl) |
| scope | `scoped`, `workspace`, `global` (sem valor: herda subject → project → workspace; nada explícito = `scoped`) |
| origin | `user`, `code`, `agent` (padrão `agent`) |
| relação | `related_to`, `depends_on`, `implements`, `references`, `supersedes`, `derived_from` |
| feedback (outcome) | `helped`, `irrelevant`, `wrong`, `outdated`, `verified` |

Key: `<tipo>/<nome>` (nome em minúsculas com `-`); fora do padrão grava com aviso, e a key de um item existente nunca muda.

Modelo do `content` (só avisa): `rule/decision` → `## Por quê`, `## Alternativa descartada`; `rule/pattern` → `Arquivo-modelo:`; `howto/troubleshoot` → `## Sintoma`, `## Causa`, `## Solução`; `context/environment` → ao menos um item em `links`.

### Scope e herança

| `scope` | Vale para |
|---|---|
| `scoped` | só o project onde o item mora |
| `workspace` | todos os projects do mesmo workspace |
| `global` | qualquer repositório, de qualquer workspace |

O scope efetivo de um item é o primeiro explícito subindo item → subject → project → workspace;
nada explícito é `scoped`. `workspace_update`, `project_update` e `subject_update` com `scope=`
mudam o alcance de tudo que herda, sem mover arquivo. Na busca, o item do project do repositório
pesa 1.0; o de scope `workspace` de outro project do mesmo workspace, 0.85; o `global` de fora,
0.7; o resto é invisível.

### Ciclo de vida

Sem aprovação: o que o agente grava já vale. Para corrigir, regrave pela mesma `key`; para
aposentar, `status: "archived"` ou uma relação `supersedes` (que arquiva o alvo). Itens
`archived` e vencidos (`ttl_days`) saem da busca e do contexto; `review` continua aparecendo,
depois e marcado. O servidor nunca apaga sozinho: `item_delete` sem chaves lista candidatos
(vencidos, arquivados há 90 dias, em revisão há 14, nunca abertos, marcados como irrelevantes) e
só remove com `confirm=True`; item `origin: "user"` nunca é candidato.

## Ferramentas (32)

| Ferramenta | Faz |
|---|---|
| `connection_create` · `connection_list` · `connection_delete` | cria (a única forma de criar), lista ou tira do cadastro uma conexão — apagar não mexe na pasta |
| `workspace_list` · `workspace_create` · `workspace_update` · `workspace_merge` · `workspace_delete` | organização dos workspaces; `create`/`update` aceitam `description` e `scope` |
| `project_list` · `project_create` · `project_update` · `project_merge` · `project_delete` | o mesmo, por workspace (a lista traz os subjects) |
| `subject_list` · `subject_create` · `subject_update` · `subject_merge` · `subject_delete` | o mesmo, por project |
| `repo` | `action="link"`, `"list"`, `"unlink"` ou `"sync"`: liga o repositório a um workspace/project, ou puxa o que mudou no remote |
| `item_search` | busca explicada pelo alcance, até 5 consultas por chamada, com `paths`, `scope` e filtros |
| `item_get` | itens completos por keys ou ids, vários de uma vez |
| `item_save` | cria, atualiza, regrava por `key`, move; até 20 itens, atômico |
| `item_delete` | candidatos à limpeza, prévia e remoção com `confirm=True` |
| `item_feedback` | diz o que cada item fez por você (`helped`, `irrelevant`, `wrong`, `outdated`, `verified`) |
| `item_graph` | vizinhança por relações, até 3 saltos |
| `relation_create` · `relation_delete` | relações em lote entre itens |
| `tag_list` · `tag_create` · `tag_update` · `tag_delete` | tags gerenciadas: contagem, renomear/mesclar, prévia ao apagar |
| `health_check` | versão, conexões, arquivos que não leram e `gh` autenticado |

Todas aceitam `connection_id` opcional, menos `connection_*` e `health_check`. Guia por tarefa,
com exemplos: [docs/MCP_USAGE.md](docs/MCP_USAGE.md).

## Conexões: cada uma é um repositório git

Cada item não secreto vira um arquivo Markdown com frontmatter YAML na pasta da conexão. A
leitura é direta dos arquivos (com um cache em memória por arquivo, invalidado por data e
tamanho), então editar, apagar ou puxar arquivos por fora também vale. Um arquivo que não lê não
derruba nada: aparece em `parse_errors` do `health_check`.

`review_mode`, por conexão:

- `direct` (padrão): as escritas comitam direto na branch principal (com push, se houver
  `remote_url`).
- `pr`: a mesma gravação vai para uma branch nova e abre um Pull Request (ou uma Issue, se o
  token não tiver permissão de push); a resposta traz `pending_review`/`pr_url` (ou
  `issue_opened`/`issue_url`) em vez do resultado de sempre — a mudança aparece depois que o PR
  for mergeado e alguém rodar `repo(action="sync")`.

## CLI

```bash
knowledge-mcp                                   # servidor MCP (stdio)
knowledge-mcp context --repo . --paths src/payments/Charge.java --budget 1500
knowledge-mcp context --hook claude|cursor      # hook de início de sessão (lê o JSON no stdin)
knowledge-mcp link --repo .                     # project = repo; workspace = o do dono
knowledge-mcp recent --since 2026-10-01 --json  # o que mudou (usado pela daily)
knowledge-mcp report --json                     # o que revisar no cérebro (usado pelo dream)
knowledge-mcp pending --repo .                  # grava a fila offline (~/.knowledge-os/pending.jsonl)
knowledge-mcp ui [--port 8765]                  # UI web local (127.0.0.1; já sobe com o MCP)
knowledge-mcp run --env NPM_TOKEN=secret/npm-token -- npm publish   # segredo só no filho
knowledge-mcp --version
```

Os subcomandos do cérebro não carregam o servidor MCP: o hook responde em ~1 s.

**Pacote de contexto** (`context`): pelo mesmo alcance da busca, nesta ordem — Em foco (o que
casa `--paths`/`--query`, com o começo do `content`), Em revisão, Segurança (`rule/security`),
Regras por subtipo, Contexto, Como fazer (só títulos), Specs ativas, Segredos (estado e como
usar) e Regras com escopo (as de `scope_paths` que casam). Item de fora do project do
repositório leva a origem (`[global]` ou `[<workspace>]`). Respeita o orçamento em tokens e lista
o que ficou de fora. Sem conexão, devolve o exemplo de `connection_create`; o hook nunca derruba
a sessão.

**Relatório** (`report --json`): `never_opened_60d`, `review_over_7d`, `high_irrelevant`,
`empty_searches` (as buscas que voltaram vazias, com contagem) e `tags_unused`, cada lista com
`key`, `where` e o motivo.

## UI

`knowledge-mcp ui` (ou o servidor MCP, que já a sobe) abre uma UI local em
`http://127.0.0.1:8765`. Mostra os itens com tipo e subtipo, o scope (com o herdado indicado), a
marca de "em revisão", `links`, `origin` e as ligações do item em grafo; as tags com contagem; a
organização em workspaces, projects e subjects com `scope`; e as conexões, com o caminho da pasta.
É também onde você preenche o valor de um segredo. Só escuta em `127.0.0.1`.

## Segredos

Token, senha ou chave de API viram um item `secret` (key `secret/<nome>`), no mesmo esquema do
resto: no project do repositório, ou com `scope` maior para compartilhar. O fluxo:

1. O agente grava o item **sem valor** (`item_save` recusa qualquer campo de valor) e a resposta
   traz `fill_url`, o link da UI local direto no item.
2. Você abre o link e cola o valor num campo de senha. Ele é cifrado (Fernet) e guardado à parte,
   em `<pasta-da-conexão>/.secrets/<item_id>.enc` (fora do git); nenhuma ferramenta, rota,
   busca ou contexto o devolve — só `has_value`. Na UI dá para substituir ou apagar; não existe
   "revelar".
3. O agente usa: `knowledge-mcp run --env VAR=secret/<nome> [--stdin secret/<nome>] -- <comando>`.
   O valor vai só para o ambiente (ou stdin) do filho, que roda sem shell e sem a chave mestra;
   a saída volta com o valor e as codificações comuns (base64, URL) trocados por `***`. A key é
   procurada pelo mesmo alcance da busca. A redação cobre o valor exato, base64 (inclusive
   dentro de `Basic user:token`), URL, JSON escapado, as codepages do Windows e UTF-16, e cada
   linha de um valor de várias linhas.

A chave mestra é aleatória e fica no keyring do sistema (no Windows, o Gerenciador de
Credenciais). `KNOWLEDGE_OS_VAULT_KEY` existe só para CI e máquinas sem keyring — nunca a
ponha na config do MCP (`.mcp.json`) nem no ambiente do agente: quem a lê, com a pasta
`.secrets/`, abre todos os valores. Os arquivos `.enc` guardam só texto cifrado, cada valor
amarrado ao seu item. Se a chave some depois de criada, o servidor dá erro em vez de gerar outra
por cima.

No Windows, o `run` acha o comando só pelo PATH (nunca pela pasta do projeto, onde um `gh.cmd`
plantado receberia o token). Comandos `.cmd`/`.bat` (npm, az...) rodam pelo `cmd.exe`: o `run`
recusa argumentos com `" % & | < > ^ !` nesses casos. Valores com menos de 4 caracteres são
recusados (não daria para escondê-los na saída).

**Modelo de ameaça.** Protege o valor do contexto do modelo, do histórico das conversas, dos
itens e do repositório git. **Não** protege contra: um agente ou comando feito para vazar (quem
roda `knowledge-mcp run` pode escrever um filho que imprime o valor transformado de um jeito que
a redação não reconhece); malware rodando com o seu usuário (lê o keyring e chama a UI local); o
próprio comando gravar o valor em log ou arquivo. Segredo nunca expira sozinho.

Conteúdo com cara de segredo (chaves de nuvem, tokens, chaves privadas, `password=...`,
URLs com senha) em itens comuns é recusado sem eco do valor (a mensagem ensina o fluxo de
segredos acima).

## Desenvolvimento

```bash
uv pip install -e ".[dev]"
pytest -q                 # inclusive ponta a ponta via stdio
ruff check src tests
```

Arquitetura: [docs/ARQUITETURA.md](docs/ARQUITETURA.md). O contrato da v2 está em
[docs/V2_MVP.md](docs/V2_MVP.md). Mudanças são conduzidas pelo Plumb (o plano de cada mudança
fica guardado no próprio cérebro).

## Licença

MIT
