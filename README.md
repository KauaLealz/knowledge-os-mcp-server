# Knowledge OS — segundo cérebro para agentes

Servidor MCP local que guarda o conhecimento durável do seu trabalho — regras, decisões e o
porquê, procedimentos, contexto e aprendizados — e o devolve aos agentes com pouco custo de
contexto. É a memória obrigatória do [Plumb](https://github.com/KauaLealz/plumb-harness):
o hook de início de sessão injeta o contexto do projeto e o fechamento de cada mudança grava
o que valeu, numa chamada.

- **Local-first:** SQLite em `~/.knowledge-os` (Postgres e MySQL opcionais, pela UI).
- **Barato em contexto:** 14 ferramentas, sempre as mesmas para qualquer cliente MCP, com
  instruções curtas; o pacote de contexto respeita um orçamento.
- **Busca sem embeddings que acerta em PT-BR:** FTS5 sem acento, radical e prefixo
  ("migração" acha "migrações"), relevância antes de importância.
- **Escrita idempotente:** `item_save` em lote, por `key` estável — grava de novo sem duplicar.
- **Segredos sem passar pelo modelo:** o agente cria o segredo vazio, você preenche na UI
  local e ele usa por `knowledge-mcp run`, que entrega o valor só ao processo filho.
- **Seguro:** recusa segredos em itens comuns; operações destrutivas pedem confirmação.

## Instalar

```bash
uv tool install "git+https://github.com/KauaLealz/knowledge-os-mcp-server"      # comando `knowledge-mcp`
knowledge-mcp --version
```

Para desenvolver, clone e instale editável: `uv tool install --editable <pasta-do-clone>`.

O SQLite (padrão) já vem incluído. Os drivers de Postgres e MySQL são opcionais:

```bash
uv tool install "knowledge-mcp[postgres] @ git+https://github.com/KauaLealz/knowledge-os-mcp-server"   # ou [mysql], ou [all]
```

Sem o driver, conectar a esse banco falha com a mensagem "instale knowledge-mcp[postgres]"
(ou `[mysql]`).

Já tinha instalado antes do layout `src/knowledge_os/`? O comando antigo segue funcionando por
um atalho, com aviso no stderr; reinstale com `uv tool install --editable <caminho-do-repo> --force`.

O instalador do Plumb (`npx plumb-harness install`) registra o servidor no Claude Code e no
Cursor, com o hook de início de sessão. Para registrar à mão:

```bash
claude mcp add --scope user knowledge-os -e LOG_LEVEL=WARNING -- knowledge-mcp
```

```json
// ~/.cursor/mcp.json
{ "mcpServers": { "knowledge-os": { "command": "knowledge-mcp",
  "env": { "LOG_LEVEL": "WARNING" } } } }
```

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

Um repositório é ligado a um workspace/project pela chave do remote do git
(ferramenta `repo(action="link")`, ou `knowledge-mcp link`).

## Ferramentas

As 14 ferramentas abaixo são sempre registradas, para qualquer cliente MCP:

| Ferramenta | Faz |
|---|---|
| `workspace` | lista, cria, renomeia, mescla ou apaga workspaces |
| `project` | lista, cria, renomeia, mescla ou apaga projects de um workspace |
| `subject` | lista, cria, renomeia, mescla ou apaga subjects de um project |
| `repo` | liga, lista ou desliga repositórios de um workspace/project |
| `context_get` | pacote do projeto (regras, contexto, decisões, padrões, procedimentos, aprendizados) dentro de um orçamento |
| `item_search` | busca por texto; devolve resumos |
| `item_get` | itens completos por ids ou keys, vários de uma vez |
| `item_save` | criar, atualizar, upsert, mover, lote e relacionar — numa transação |
| `item_delete` | remove um item de vez, com tags, relações e anexos |
| `relation_delete` | remove uma relação entre itens |
| `vocabulary` | tags e labels da base |
| `artifact` | anexa um arquivo a um item ou lê um anexo existente |
| `backup` | exporta um workspace/project para ZIP, ou importa um ZIP desses |
| `health_check` | versão e schema do banco |

Conexões com outros bancos, sincronização de schema e migração ficam na UI. Guia completo:
[docs/MCP_USAGE.md](docs/MCP_USAGE.md).

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
knowledge-mcp --check-db | --bootstrap | --migrate-v2 | --version
```

Os subcomandos do cérebro não carregam o servidor MCP: o hook responde em ~1 s.

## Segredos

Token, senha ou chave de API viram um item `secret` (key `segredo/<nome>`), no mesmo esquema do
resto: no project do repositório, no `Geral` do workspace (compartilhado pelos repos da empresa)
ou no `Global` (seus). O fluxo:

1. O agente grava o item **sem valor** (`item_save` recusa qualquer campo de valor) e a resposta
   traz `fill_url`, o link da UI local direto no item.
2. Você abre o link e cola o valor num campo de senha. Ele é cifrado (Fernet) e guardado à parte
   (`secret_values`); nenhuma ferramenta, rota, busca, contexto ou exportação o devolve — só
   `has_value`. Na UI dá para substituir ou apagar; não existe "revelar".
3. O agente usa: `knowledge-mcp run --env VAR=segredo/<nome> [--stdin segredo/<nome>] -- <comando>`.
   O valor vai só para o ambiente (ou stdin) do filho, que roda sem shell e sem a chave mestra;
   a saída volta com o valor e as codificações comuns (base64, URL) trocados por `***`. A key é
   procurada no repo, depois no `Geral` do workspace, depois no `Global`. A redação cobre o
   valor exato, base64 (inclusive dentro de `Basic user:token`), URL, JSON escapado, as
   codepages do Windows e UTF-16, e cada linha de um valor de várias linhas.

A chave mestra é aleatória e fica no keyring do sistema (no Windows, o Gerenciador de
Credenciais). `KNOWLEDGE_OS_VAULT_KEY` existe só para CI e máquinas sem keyring — nunca a
ponha na config do MCP (`.mcp.json`) nem no ambiente do agente: quem a lê, com o banco, abre
todos os valores. O banco e os backups guardam só texto cifrado, cada valor amarrado ao seu
item. Se a chave some depois de criada, o servidor dá erro em vez de gerar outra por cima.

No Windows, o `run` acha o comando só pelo PATH (nunca pela pasta do projeto, onde um `gh.cmd`
plantado receberia o token). Comandos `.cmd`/`.bat` (npm, az...) rodam pelo `cmd.exe`: o `run`
recusa argumentos com `" % & | < > ^ !` nesses casos. Valores com menos de 4 caracteres são
recusados (não daria para escondê-los na saída).

**Modelo de ameaça.** Protege o valor do contexto do modelo, do histórico das conversas, dos
itens, das exportações e do arquivo do banco. **Não** protege contra: um agente ou comando feito
para vazar (quem roda `knowledge-mcp run` pode escrever um filho que imprime o valor
transformado de um jeito que a redação não reconhece); malware rodando com o seu usuário (lê o
keyring e chama a UI local); o próprio comando gravar o valor em log ou arquivo. Segredo nunca
expira sozinho.

## Dados e segurança

Tudo fica no home (`KNOWLEDGE_OS_HOME`, padrão `~/.knowledge-os`): `knowledge.db`,
`connections.json`, `artifacts/`, `exports/`, `backups/`. Senhas de conexões ficam no
`connections.json` (fora de qualquer repositório) e nunca passam pelas ferramentas.
Conteúdo com cara de segredo (chaves de nuvem, tokens, chaves privadas, `password=...`,
URLs com senha) em itens comuns é recusado sem eco do valor (a mensagem ensina o fluxo de
segredos acima). Com `MCP_DB_KEY` e o extra `crypto`, o catálogo
é criptografado com SQLCipher (Linux).

## Desenvolvimento

```bash
uv pip install -e ".[dev]"
pytest -q                 # ~490 testes, inclusive ponta a ponta via stdio
ruff check src tests
```

Arquitetura: [docs/ARQUITETURA.md](docs/ARQUITETURA.md). Mudanças são conduzidas pelo
Plumb (o plano de cada mudança fica no próprio cérebro, como item `task`).

## Licença

MIT
