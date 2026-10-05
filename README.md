# Knowledge OS — segundo cérebro para agentes

Servidor MCP local que guarda o conhecimento durável do seu trabalho — regras, decisões e o
porquê, procedimentos, contexto e aprendizados — e o devolve aos agentes com pouco custo de
contexto. É a memória obrigatória do [Plumb](https://github.com/KauaLealz/plumb-harness):
o hook de início de sessão injeta o contexto do projeto e o fechamento de cada mudança grava
o que valeu, numa chamada.

- **Local-first:** SQLite em `~/.knowledge-os` (Postgres e MySQL opcionais, pela UI).
- **Barato em contexto:** perfil `agent` com 6 ferramentas (~1.800 tokens de definição) e
  instruções de ~400 tokens; o pacote de contexto respeita um orçamento.
- **Busca sem embeddings que acerta em PT-BR:** FTS5 sem acento, radical e prefixo
  ("migração" acha "migrações"), relevância antes de importância.
- **Escrita idempotente:** `item_save` em lote, por `key` estável — grava de novo sem duplicar.
- **Seguro:** recusa segredos no conteúdo; operações destrutivas pedem confirmação.

## Instalar

```bash
uv tool install --editable <caminho-do-repo>      # comando `knowledge-mcp`
knowledge-mcp --version
```

O instalador do Plumb (`npx plumb-harness install`) registra o servidor no Claude Code e no
Cursor, com o perfil `agent` e o hook de início de sessão. Para registrar à mão:

```bash
claude mcp add --scope user knowledge-os -e KNOWLEDGE_OS_TOOLSET=agent -e LOG_LEVEL=WARNING -- knowledge-mcp
```

```json
// ~/.cursor/mcp.json
{ "mcpServers": { "knowledge-os": { "command": "knowledge-mcp",
  "env": { "KNOWLEDGE_OS_TOOLSET": "agent", "LOG_LEVEL": "WARNING" } } } }
```

## Modelo

```
Workspace (cliente, empresa, área)        ex.: Polara
 └── Domain (um projeto ou tópico)         ex.: projpro · Geral (vale para todo o workspace)
      └── Item: type · memory_class · key · title · summary · content · scope_paths · source
Global / Geral                             preferências que valem em todo projeto
```

| type | Para |
|---|---|
| `rule` | sempre/nunca (com `scope_paths` quando vale só para parte do código) |
| `insight` | decisão e o porquê |
| `procedure` | passo a passo |
| `pattern` · `knowledge` · `context` | solução recorrente · fato/gotcha · pano de fundo |

`memory_class`: `ephemeral` (com TTL) → `working` (rascunho) → `longterm` → `canonical`.
Só sobe. Itens substituídos (`supersedes`) e obsoletos saem da busca e do contexto.

Um repositório é ligado a um workspace/domain pela chave do remote do git
(`project_link`, ou `knowledge-mcp link`).

## Ferramentas

| Perfil `agent` (padrão do Plumb) | |
|---|---|
| `context_get` | pacote do projeto (regras, contexto, decisões, padrões, procedimentos, aprendizados) dentro de um orçamento; `paths` traz as regras com escopo |
| `item_search` | busca por texto; devolve resumos |
| `item_get` | itens completos por ids ou keys, vários de uma vez |
| `item_save` | criar, atualizar, upsert, lote, promover, renovar e relacionar — numa transação |
| `project_link` | liga um repositório a workspace/domain |
| `health_check` | versão, schema e perfil |

Perfil `all` (padrão sem a variável): + `structure_list`, `structure_delete` (preview e
`confirm`), `item_delete`, `relation_delete`, `vocabulary` (tags/labels), `backup_export`,
`backup_import`, `artifact_attach`, `artifact_get`. Conexões com outros bancos, sincronização
de schema e migração ficam na UI. Guia completo: [docs/MCP_USAGE.md](docs/MCP_USAGE.md).

## CLI

```bash
knowledge-mcp                                   # servidor MCP (stdio)
knowledge-mcp context --project . --paths src/payments/Charge.java --budget 1500
knowledge-mcp context --hook claude|cursor      # hook de início de sessão (lê o JSON no stdin)
knowledge-mcp link --project . --workspace Polara --domain projpro
knowledge-mcp recent --since 2026-10-01 --json  # o que mudou (usado pela daily)
knowledge-mcp pending --project .               # grava a fila .plumb/pending-brain.jsonl
knowledge-mcp ui [--port 8765]                  # UI web local (127.0.0.1)
knowledge-mcp --check-db | --bootstrap | --version
```

Os subcomandos do cérebro não carregam o servidor MCP: o hook responde em ~1 s.

## Dados e segurança

Tudo fica no home (`KNOWLEDGE_OS_HOME`, padrão `~/.knowledge-os`): `knowledge.db`,
`connections.json`, `artifacts/`, `exports/`, `backups/`. Senhas de conexões ficam no
`connections.json` (fora de qualquer repositório) e nunca passam pelas ferramentas.
Conteúdo com cara de segredo (chaves de nuvem, tokens, chaves privadas, `password=...`,
URLs com senha) é recusado sem eco do valor. Com `MCP_DB_KEY` e o extra `crypto`, o catálogo
é criptografado com SQLCipher (Linux).

## Desenvolvimento

```bash
uv pip install -e ".[dev]"
pytest -q                 # ~490 testes, inclusive ponta a ponta via stdio
ruff check src tests
```

Arquitetura: [docs/ARQUITETURA.md](docs/ARQUITETURA.md). Mudanças são conduzidas pelo
Plumb (`.plumb/changes/`).

## Licença

MIT
