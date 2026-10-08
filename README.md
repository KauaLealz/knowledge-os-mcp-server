# Knowledge OS — segundo cérebro para agentes

Servidor MCP local que guarda o conhecimento durável do seu trabalho — regras, decisões e o
porquê, procedimentos, contexto e aprendizados — e o devolve aos agentes com pouco custo de
contexto. É a memória obrigatória do [Plumb](https://github.com/KauaLealz/plumb-harness):
o hook de início de sessão injeta o contexto do projeto e o fechamento de cada mudança grava
o que valeu, numa chamada.

- **Só arquivos, num repositório git seu:** cada conexão é uma pasta (repositório git) que você
  escolhe; cada item é um arquivo Markdown com frontmatter YAML, e cada escrita é um commit. Nada
  persiste fora da pasta para ser reconstruído: o que está nela é a verdade.
- **Barato em contexto:** as mesmas ferramentas para qualquer cliente MCP, com instruções
  curtas; o pacote de contexto respeita um orçamento.
- **Busca sem embeddings que acerta em PT-BR:** em memória, sem acento, por radical e prefixo
  ("migração" acha "migrações"), relevância antes de importância.
- **Escrita idempotente:** `item_save` em lote, por `key` estável — grava de novo sem duplicar.
- **Segredos sem passar pelo modelo:** o agente cria o segredo vazio, você preenche na UI
  local e ele usa por `knowledge-mcp run`, que entrega o valor só ao processo filho.
- **Seguro:** recusa segredos em itens comuns; operações destrutivas pedem confirmação.

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

## Onde ficam os dados

- **Na pasta de cada conexão** (o repositório git que você escolheu): todos os itens, como
  `<workspace>/<project>/<key>.md`, os `.knowledge.yaml` de workspaces, projects, tags e labels,
  e os valores de segredos cifrados em `.secrets/` (no `.gitignore`: nunca entram no git).
- **No home** (`KNOWLEDGE_OS_HOME`, padrão `~/.knowledge-os`), só estado desta máquina:
  `connections.json` (as conexões e a padrão), `repos.json` (repositório local → conexão,
  workspace e project), `usage/` (contador de uso por item), `locks/` (travas de escrita entre
  processos), a fila offline `pending.jsonl` e marcas pequenas (como a da manutenção diária).
  Nenhum item fica aí.

Fazer backup ou levar para outra máquina é o mesmo que com qualquer repositório git: commit,
push, clone.

## Modelo

```
Workspace = contexto de trabalho     ex.: Polara (empresa), Pessoal
 ├── Project Geral                     o que vale para todos os repositórios do workspace
 └── Project = um repositório          ex.: projpro, synapse
      └── Subject (opcional)           agrupador de assunto dentro do project, ex.: pagamentos
           └── Item: type · key · title · summary · content · scope_paths · keywords · source
Global / Geral                        o que vale para você em qualquer lugar
```

| type | Para |
|---|---|
| `rule` | sempre/nunca (com `scope_paths` quando vale só para parte do código) |
| `insight` | decisão e o porquê |
| `procedure` | passo a passo |
| `pattern` · `knowledge` · `context` | solução recorrente · fato/gotcha · pano de fundo |

Sem aprovação: o que o agente grava já vale. Para corrigir, regrave pela mesma `key`; para
aposentar, `status: deprecated` ou `supersedes` — itens substituídos e obsoletos saem da busca e
do contexto. Nota temporária: `memory_class: "ephemeral"` com `ttl_days` — a manutenção diária
apaga quando o TTL vence. O resto (aprendizado, regra, decisão, procedimento) nunca expira
sozinho; cada entrega a um agente conta em `uses`, e a `/plumb-retro` mostra o que nunca foi usado.

## Ferramentas

| Ferramenta | Faz |
|---|---|
| `connection_create` · `connection_list` · `connection_delete` | cria (a única forma de criar), lista ou tira do cadastro uma conexão — apagar não mexe na pasta |
| `workspace_*` · `project_*` · `subject_*` | list, create, rename, merge e delete de workspaces, projects e subjects |
| `repo` | liga, lista ou desliga repositórios de um workspace/project; `action="sync"` puxa o que mudou no remote da conexão |
| `context_get` | pacote do projeto (regras, contexto, decisões, padrões, procedimentos, aprendizados) dentro de um orçamento |
| `item_search` | busca por texto; devolve resumos |
| `item_get` | itens completos por ids ou keys, vários de uma vez |
| `item_save` | criar, atualizar, upsert, mover, lote e relacionar — numa publicação só |
| `item_delete` | remove um item de vez, com tags e relações |
| `relation_create` · `relation_delete` | cria ou remove uma relação entre itens |
| `tag_*` · `label_*` | list, create e delete de tags e labels |
| `health_check` | versão, conexão padrão (pasta existe / é repositório git) e `gh` autenticado |

Guia completo: [docs/MCP_USAGE.md](docs/MCP_USAGE.md).

## Conexões: cada uma é um repositório git

Cada item não secreto vira um arquivo Markdown com frontmatter YAML na pasta da conexão. A
leitura é direta dos arquivos (com um cache em memória por arquivo, invalidado por data e
tamanho), então editar, apagar ou puxar arquivos por fora também vale.

`review_mode`, por conexão:

- `direct` (padrão): `item_save`/`item_delete`/`relation_delete` escrevem e commitam direto na
  branch principal (com push, se houver `remote_url`).
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
knowledge-mcp pending --repo .                   # grava a fila offline (~/.knowledge-os/pending.jsonl)
knowledge-mcp ui [--port 8765]                  # UI web local (127.0.0.1; já sobe com o MCP)
knowledge-mcp run --env NPM_TOKEN=segredo/npm-token -- npm publish   # segredo só no filho
knowledge-mcp --version
```

Os subcomandos do cérebro não carregam o servidor MCP: o hook responde em ~1 s.

## Segredos

Token, senha ou chave de API viram um item `secret` (key `segredo/<nome>`), no mesmo esquema do
resto: no project do repositório, no `Geral` do workspace (compartilhado pelos repos da empresa)
ou no `Global` (seus). O fluxo:

1. O agente grava o item **sem valor** (`item_save` recusa qualquer campo de valor) e a resposta
   traz `fill_url`, o link da UI local direto no item.
2. Você abre o link e cola o valor num campo de senha. Ele é cifrado (Fernet) e guardado à parte,
   em `<pasta-da-conexão>/.secrets/<item_id>.enc` (coberto por `.gitignore`: nunca entra no
   git); nenhuma ferramenta, rota, busca ou contexto o devolve — só `has_value`. Na UI dá para
   substituir ou apagar; não existe "revelar".
3. O agente usa: `knowledge-mcp run --env VAR=segredo/<nome> [--stdin segredo/<nome>] -- <comando>`.
   O valor vai só para o ambiente (ou stdin) do filho, que roda sem shell e sem a chave mestra;
   a saída volta com o valor e as codificações comuns (base64, URL) trocados por `***`. A key é
   procurada no repo, depois no `Geral` do workspace, depois no `Global`. A redação cobre o
   valor exato, base64 (inclusive dentro de `Basic user:token`), URL, JSON escapado, as
   codepages do Windows e UTF-16, e cada linha de um valor de várias linhas.

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

Arquitetura: [docs/ARQUITETURA.md](docs/ARQUITETURA.md). Mudanças são conduzidas pelo
Plumb (o plano de cada mudança fica guardado no próprio cérebro).

## Licença

MIT
