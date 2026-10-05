# How to Use Knowledge OS MCP

Guia prático, orientado a tarefas. Para o modelo conceitual (connection,
workspace, domain, item...), tipos, classes de memória e a tabela
"qual tool usar", veja `src/mcp/INSTRUCTIONS.md`. Os parâmetros de cada tool
estão no docstring do próprio tool.

> **Notação.** Os exemplos usam `mcp call <tool> --parametro valor` como forma
> compacta de mostrar uma chamada de tool. Em um cliente MCP real (Claude
> Desktop, Claude Code etc.) é o mesmo tool com os mesmos parâmetros, só que
> chamado pelo cliente. Os ids (`ws_...`, `item_...`) são ilustrativos: use os
> que o servidor devolver.

## Installation

```bash
pip install -e .          # instala as dependências (veja pyproject.toml)
python src/main.py        # inicia o servidor MCP (stdio)
```

Na inicialização o servidor escreve em **stderr** (o stdout é o canal do protocolo):

```
Loaded: <home>/connections.json
Connected: <nome da conexão> (<id>)
```

Comandos úteis antes de subir o servidor:

```bash
python src/main.py --bootstrap   # cria schema e labels padrão e sai
python src/main.py --check-db    # verifica conexão e schema e sai
```

Para registrar o servidor num cliente MCP, aponte o comando para
`python src/main.py` (transporte stdio).

## Quick Start (5 minutos)

### 1. Criar um workspace
```bash
mcp call workspace_create --name "Learning Python"
# Retorna: {"id": "ws_abc123", "name": "Learning Python", ...}
```

### 2. Criar um domain dentro dele
```bash
mcp call domain_create --workspace "Learning Python" --name "Decorators"
# Retorna: {"id": "dom_xyz789", "name": "Decorators", ...}
```

### 3. Guardar conhecimento
```bash
mcp call item_create \
  --workspace "Learning Python" \
  --domain "Decorators" \
  --type knowledge \
  --memory-class longterm \
  --title "O que é um decorator?" \
  --summary "Função que envolve outra função para estender seu comportamento" \
  --content "# Decorators em Python\n\nSintaxe @nome sobre uma função..."
# Retorna: {"id": "item_def456", ...}
```

### 4. Buscar depois
```bash
mcp call item_search --workspace "Learning Python" --query "decorator"
# Retorna: [{"id": "item_def456", "title": "O que é um decorator?", "summary": "...", "score": 0.95}]

mcp call item_get --item-id item_def456     # conteúdo completo
```

> `workspace` e `domain` são passados **pelo nome**. `item_search` nunca devolve
> o `content`; use `item_get` para lê-lo.

## Workflows

### Workflow 1: Guardar & Buscar Conhecimento

**Objetivo:** documentar um aprendizado e reutilizá-lo depois.

```bash
# 1. Criar contexto e tópico (pule se já existirem: workspace_list / domain_list)
mcp call workspace_create --name "Python"
mcp call domain_create --workspace "Python" --name "Async"

# 2. Guardar o item, já com tags
mcp call item_create \
  --workspace "Python" --domain "Async" \
  --type knowledge --memory-class working \
  --title "asyncio básico" \
  --summary "Event loop, coroutines e await" \
  --content "..." \
  --tags '["asyncio", "python"]' \
  --importance 7
# Retorna: {"id": "item_abc", ...}

# 3. Buscar depois
mcp call item_search --workspace "Python" --query "asyncio"

# 4. Ler o conteúdo do resultado
mcp call item_get --item-id item_abc

# 5. Quando o conhecimento se provar útil, promover
mcp call memory_promote --item-id item_abc --target-memory longterm
```

Tags e labels entram **na criação** do item. Para ver o vocabulário existente:
`mcp call tag_list` e `mcp call label_list`.

---

### Workflow 2: Migrar de SQLite para PostgreSQL

**Objetivo:** mover o conhecimento para um servidor remoto.

```bash
# 1. Registrar a connection PostgreSQL
mcp call connection_create \
  --name "postgres_prod" \
  --db-type postgresql \
  --url "postgresql://user@prod.example.com:5432/knowledge"
# A senha não entra aqui: informe-a na UI (Configurações > Conexões) ou no campo
# `password` do connections.json.

# 2. Testar a conexão
mcp call connection_test --connection-id postgres_prod
# Retorna: {"status": "ok", "message": "connected", "latency_ms": 42}

# 3. Preparar o banco (cria tabelas e índices; idempotente)
mcp call schema_sync --connection-id postgres_prod

# 4. Migrar tudo (replace: limpa o destino antes de copiar)
mcp call migrate_workspaces \
  --from-connection-id sqlite_backup \
  --to-connection-id postgres_prod \
  --mode replace

# 5. Conferir
mcp call workspace_list --connection-id postgres_prod
```

Escolha do `mode`:

| mode | O que faz | Quando usar |
|------|-----------|-------------|
| `replace` | Apaga os dados do destino e copia tudo | Destino vazio ou descartável |
| `merge` | Une tags/labels por nome e adiciona o resto; aborta se algum id já existir | Destino já tem dados que você quer manter |

Depois da migração, passe `--connection-id postgres_prod` nos demais tools
para operar no PostgreSQL. Faça um backup (Workflow 4) antes de usar `replace`
num destino com dados.

---

### Workflow 3: Conectar Ideias com Relations

**Objetivo:** rastrear dependências entre conhecimentos.

```bash
# Ter dois items: item_A e item_B (ids vindos de item_create ou item_search)

# item_A depende de item_B
mcp call relation_create \
  --source-id item_A \
  --target-id item_B \
  --relation-type depends_on
# Retorna: {"id": "rel_001", "source_item_id": "item_A", "target_item_id": "item_B", "relation_type": "depends_on"}

# Ver as relações de item_A (como origem ou destino)
mcp call relation_list --item-id item_A

# Desfazer
mcp call relation_delete --relation-id rel_001
```

Tipos: `related_to`, `depends_on`, `implements`, `references`, `supersedes`,
`derived_from`. A direção vai de `source` para `target`.

---

### Workflow 4: Exportar & Importar (Backup/Share)

**Objetivo:** fazer backup ou compartilhar um workspace inteiro.

```bash
# Dados do workspace (manifest + conteúdo), para inspeção
mcp call workspace_export --name "Python"
# Retorna: {"status": "ok", "manifest": {...}, "workspace": {...}}

# Restaurar a partir de um ZIP de exportação, em qualquer connection
mcp call workspace_import \
  --file-path ./exports/python.zip \
  --connection-id postgres_prod
# Retorna: {"status": "ok", "id": "...", "name": "Python", ...}
```

Pontos de atenção:

- `workspace_import` **cria um workspace novo** e falha se o nome já existir na
  connection. Renomeie ou apague o existente antes.
- O mesmo vale para um tópico isolado: `domain_export` / `domain_import
  --workspace <nome> --file-path <zip>` (falha se o domain já existir).
- Para copiar tudo entre bancos sem passar por ZIP, use o Workflow 2.
- O ZIP de exportação é gerado pelo serviço de import/export (o endpoint
  `POST /workspaces/{id}/export` da API HTTP); o tool `workspace_export` devolve
  o conteúdo estruturado.

---

## Dicas & Truques

### Listar tudo de forma rápida
```bash
mcp call connection_list                              # connections
mcp call workspace_list                               # workspaces
mcp call domain_list --workspace "Python"             # domains de um workspace
mcp call tag_list                                     # tags
mcp call label_list                                   # labels
mcp call relation_list --item-id item_abc             # relações de um item
mcp call artifact_list --item-id item_abc             # anexos de um item
```

Não existe `item_list`: para enumerar items use `item_search` com `--limit`.

### Busca avançada
```bash
# Em um domain específico
mcp call item_search --workspace "Python" --domain "Async" --query "loop"

# Só regras e padrões
mcp call item_search --workspace "Python" --query "retry" --types '["rule", "pattern"]'

# Só conhecimento consolidado, mais resultados
mcp call item_search --workspace "Python" --query "deploy" \
  --memory-classes '["longterm", "canonical"]' --limit 25
```

O resultado é ordenado por `importance`, `confidence`, `access_count` e
`updated_at`: preencha `importance`/`confidence` ao criar para que o melhor
conhecimento apareça primeiro.

### Memória e metadados
```bash
# Item completo: content, tags, labels, metadados
mcp call item_get --item-id item_abc

# Promover (ephemeral -> working -> longterm -> canonical)
mcp call memory_promote --item-id item_abc --target-memory longterm

# Estender o prazo de um item ephemeral
mcp call memory_renew --item-id item_abc --ttl-days 14

# Corrigir só alguns campos
mcp call item_update --item-id item_abc --summary "Resumo revisado" --importance 9
```

### Anexos
```bash
mcp call artifact_attach --item-id item_abc --file-path ./docs/arquitetura.pdf
mcp call artifact_list --item-id item_abc
mcp call artifact_get --artifact-id art_123    # conteúdo em base64 (até 100MB)
```

---

## Troubleshooting

| Problema | Solução |
|----------|---------|
| Connection não encontrada | Rodar `connection_list` para ver os ids disponíveis |
| Workspace/domain não encontrado | Rodar `workspace_list` / `domain_list` e usar o **nome** exato |
| Não conecta ao PostgreSQL/MySQL | `connection_test --connection-id <id>`; conferir URL, rede e a variável de ambiente da senha |
| Erro de tabela/schema ausente | `schema_sync --connection-id <id>` e depois `health_check` |
| Item `ephemeral` rejeitado | Informar `ttl_days` ao criar |
| `memory_promote` recusado | Só é possível subir de classe (nunca rebaixar nem voltar a `ephemeral`) |
| `memory_renew` recusado | Só vale para items `ephemeral` |
| Busca sem resultado | Usar menos palavras, outro `domain`, sinônimos; confirmar o `workspace` |
| `workspace_import` falha por nome | Já existe um workspace com esse nome na connection; renomeie ou remova |
| Migração falha | Garantir que o destino foi inicializado (`schema_sync`); em `merge`, ids repetidos abortam, então use `replace` num destino descartável |
| `artifact_attach` falha | O caminho precisa ser um arquivo regular existente de até 100MB |
| Servidor não inicia | `python src/main.py --check-db` mostra o problema de banco/configuração |

---

## Próximos Passos (v0.2+)

- [ ] Permissionamento (leitura/escrita por usuário)
- [ ] Auditoria de operações
- [ ] Workflow editorial (draft -> review -> approved)
- [ ] Colaboração em tempo real (WebSocket)
- [ ] Visualização do grafo de conhecimento
- [ ] Aplicativo mobile
