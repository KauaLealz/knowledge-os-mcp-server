# T10 Spec: MCP Instructions + Tool Descriptions

## Objetivo

Documentar **como usar o MCP** de forma clara, intuitiva e sem redundância. Instruções em 3 lugares estratégicos:
1. **System Prompt** (global, como tudo funciona)
2. **Tool Descriptions** (cada tool explica seu propósito)
3. **README de Uso** (workflows práticos)

---

## 1. System Prompt (`src/mcp/INSTRUCTIONS.md`)

```markdown
# Knowledge OS MCP — System Instructions

## O que é

Knowledge OS é um **servidor MCP** que expõe um banco de conhecimento pessoal/corporativo como tools.

Você gerencia **conexões** (bancos), **workspaces** (contextos), **domains** (tópicos), **items** (conhecimento) e **relações** semânticas.

## Conceitos Chave

### Connection
- Aponta para um banco de dados (SQLite local, PostgreSQL, MySQL)
- Configurado em `.knowledge/connections.json`
- Exemplo: "sqlite_local", "postgres_prod"

### Workspace
- Contexto grande de conhecimento (projeto, assunto, pessoa)
- Contém N domains
- Exemplo: "Python Learning", "Company Wiki", "Personal Journal"

### Domain
- Tópico específico dentro de um workspace
- Contém N items
- Exemplo: "Decorators", "DevOps", "Architecture Decisions"

### Item
- Unidade de conhecimento (rule, pattern, procedure, insight)
- Tem tipo (knowledge, rule, pattern, procedure, artifact)
- Tem classe de memória (ephemeral, working, longterm, canonical)
- Exemplo: "O que é @Conditional no Spring", "Deploy checklist", "Why we chose PostgreSQL"

### Relation
- Conexão semântica entre items
- Tipos: related_to, depends_on, implements, references, supersedes, derived_from
- Exemplo: "item A depends_on item B"

### Tag / Label
- Tag: criada dinamicamente, qualquer string
- Label: controlada, lista fixa (official, critical, experimental, deprecated, reference)

### Artifact
- Arquivo anexado a um item (doc, image, code, etc)
- Max 100MB total por item
- Armazenado em disco, referência no banco

## Fluxo Típico (Modo Simples)

```
1. connection_list()
   → mostra conexões disponíveis
   → por padrão: "sqlite_local" (criada automaticamente)

2. workspace_list()
   → lista workspaces nessa connection
   → vazio no início

3. workspace_create(name="Projeto X")
   → cria novo workspace

4. domain_create(workspace_id, name="Tópico Y")
   → cria domain dentro do workspace

5. item_create(workspace, domain, title="Conhecimento Z")
   → cria item com conteúdo Markdown

6. item_search(query="padrão spring")
   → busca full-text (FTS5/tsvector conforme DB)

7. item_get(id)
   → detalhes completos, relações, tags, labels
```

## Fluxo Avançado (Multi-Conexões)

```
1. connection_create("postgres_prod", "postgresql", "postgresql://...")
   → adiciona nova connection
   → salva em `.knowledge/connections.json`

2. connection_test("postgres_prod")
   → valida conectividade

3. connection_init_db("postgres_prod")
   → cria schema no banco novo

4. workspace_list(connection_id="postgres_prod")
   → lista workspaces nessa connection (vazio no início)

5. workspace_create("Project", connection_id="postgres_prod")
   → cria workspace em PostgreSQL

6. migrate_workspaces("sqlite_local", "postgres_prod", mode="replace")
   → copia tudo de SQLite → PostgreSQL
   → depois, todos os tools usam postgres_prod
```

## Escolher entre Tools

| Objetivo | Tools | Notas |
|----------|-------|-------|
| Ver conexões | connection_list | Mostra SQLite + qualquer PostgreSQL/MySQL configurado |
| Adicionar banco remoto | connection_create | Salva em `.knowledge/connections.json` |
| Testar banco | connection_test | Verifica se tá acessível |
| Preparar banco novo | connection_init_db | Cria schema (tabelas, índices) |
| Mover dados | migrate_workspaces | SQLite → PostgreSQL, replace ou merge |
| Criar contexto | workspace_create | Use quando começar novo assunto/projeto |
| Listar contextos | workspace_list | Mostra tudo nessa connection |
| Estruturar tópico | domain_create | Use dentro de um workspace |
| Guardar conhecimento | item_create | Markdown + metadata |
| Buscar | item_search | Full-text, rápido |
| Conectar ideias | relation_create | Depende de, implementa, etc |
| Etiquetar | item_add_tags, item_add_labels | Categorizar |
| Exportar | workspace_export | ZIP com tudo (backup) |
| Importar | workspace_import | Restaurar de ZIP |

## Segurança

- **Senhas de banco:** Em `.env` (não em `.knowledge/connections.json`)
- **URLs persistidas:** Em `.knowledge/connections.json` (texto puro, local)
- **Permissionamento:** Não existe em v0.1 (v0.2+)
- **Auditoria:** Não existe em v0.1 (v0.2+)

---
```

---

## 2. Tool Descriptions (Melhorar cada Tool)

Padrão pra cada tool:

```python
@mcp.tool()
def workspace_create(
    name: str,
    description: str = None,
    connection_id: str = None
) -> dict:
    """
    Cria novo workspace (contexto grande de conhecimento).
    
    **Use quando:** 
    - Começar novo projeto/assunto/pessoa
    - Organizar conhecimento em silos
    
    **Retorna:**
    - workspace_id: use em domain_create, item_create, etc
    - name, description, created_at
    
    **Exemplo:**
    workspace_create(
        name="Python Learning",
        description="Tudo sobre Python 3.12, async, etc"
    )
    
    **Notas:**
    - Se não passar connection_id, usa default (sqlite_local)
    - Nome deve ser único dentro da connection
    - Descrição é opcional (Markdown suportado)
    """
```

Aplicar esse padrão em **TODOS os 44 tools:**
- Explicar o **propósito** (não só o que faz)
- Quando **usar** (use quando...)
- O que **retorna**
- Um **exemplo** concreto
- **Notas** importantes (constraints, limitações)

Tools prioridade de documentação:
1. **Connection:** connection_list, connection_create, connection_test, connection_init_db, migrate_workspaces
2. **Workspace:** workspace_create, workspace_list, workspace_export, workspace_import
3. **Domain:** domain_create, domain_list
4. **Item:** item_create, item_search, item_get, item_update
5. **Relations:** relation_create, relation_list
6. **Tags/Labels:** tag_create, label_create, item_add_tags
7. **Artifacts:** artifact_attach, artifact_get
8. **Memory:** memory_promote
9. **Health:** health_check

---

## 3. README de Uso (`docs/MCP_USAGE.md`)

```markdown
# How to Use Knowledge OS MCP

## Installation

```bash
pip install -r requirements.txt
python src/main.py
```

Output esperado:
```
✓ Loaded: .knowledge/connections.json
✓ Connected: Local SQLite (sqlite_local)
✓ Registered 44 MCP tools
Ready!
```

## Quick Start (5 minutos)

### 1. Criar um workspace
```bash
mcp call workspace_create --name "Learning Python"
# Retorna: {"id": "ws_abc123", "name": "Learning Python", ...}
```

### 2. Criar um domain dentro
```bash
mcp call domain_create \
  --workspace-id ws_abc123 \
  --name "Decorators"
# Retorna: {"id": "dom_xyz789", "name": "Decorators", ...}
```

### 3. Guardar conhecimento
```bash
mcp call item_create \
  --workspace-id ws_abc123 \
  --domain-id dom_xyz789 \
  --title "O que é @decorator?" \
  --type knowledge \
  --memory-class longterm \
  --content "# Decorators em Python\n\nSyntax sugar para..."
# Retorna: {"id": "item_def456", ...}
```

### 4. Buscar depois
```bash
mcp call item_search --query "decorator" --workspace-id ws_abc123
# Retorna: [{"id": "item_def456", "title": "O que é @decorator?", "score": 0.95}]
```

## Workflows

### Workflow 1: Guardar & Buscar Conhecimento

**Objetivo:** Documentar aprendizado e reutilizar depois

```bash
# 1. Criar contexto
ws=$(mcp call workspace_create --name "Python" | jq -r .id)

# 2. Criar tópico
dom=$(mcp call domain_create --workspace-id $ws --name "Async" | jq -r .id)

# 3. Guardar item
item=$(mcp call item_create \
  --workspace-id $ws \
  --domain-id $dom \
  --title "asyncio básico" \
  --content "..." | jq -r .id)

# 4. Adicionar tag
mcp call tag_create --name "asyncio" --item-id $item

# 5. Buscar depois
mcp call item_search --query "asyncio" --workspace-id $ws
```

---

### Workflow 2: Migrar de SQLite para PostgreSQL

**Objetivo:** Mover conhecimento pra servidor remoto

```bash
# 1. Criar connection PostgreSQL
mcp call connection_create \
  --name "postgres_prod" \
  --db-type postgresql \
  --url "postgresql://user:pass@prod.com/knowledge"

# 2. Testar conexão
mcp call connection_test --connection-id postgres_prod

# 3. Preparar banco (criar tabelas, índices)
mcp call connection_init_db --connection-id postgres_prod

# 4. Migrar todos os dados (replace mode)
mcp call migrate_workspaces \
  --from-connection-id sqlite_local \
  --to-connection-id postgres_prod \
  --mode replace

# 5. Verificar
mcp call connection_list
# Agora "postgres_prod" tem todos os workspaces/items/artifacts
```

---

### Workflow 3: Conectar Ideias com Relations

**Objetivo:** Rastrear dependências entre conhecimentos

```bash
# Ter dois items: item_A e item_B

# item_A depende de item_B
mcp call relation_create \
  --source-item-id item_A \
  --target-item-id item_B \
  --relation-type depends_on

# Ver relações de item_A
mcp call relation_list --item-id item_A
# Retorna: [{"type": "depends_on", "target": item_B, ...}]
```

---

### Workflow 4: Exportar & Importar (Backup/Share)

**Objetivo:** Backup ou compartilhar workspace inteiro

```bash
# Exportar workspace como ZIP
zip=$(mcp call workspace_export --workspace-id ws_abc | jq -r .file_path)
# Gera: /exports/workspace_abc_2026-10-02.zip

# Depois, importar em outra connection
mcp call workspace_import \
  --connection-id postgres_prod \
  --file-path /exports/workspace_abc_2026-10-02.zip
```

---

## Dicas & Truques

### Listar tudo de forma rápida
```bash
# Connections
mcp call connection_list

# Workspaces
mcp call workspace_list

# Domains em um workspace
mcp call domain_list --workspace-id ws_abc

# Items em um domain
mcp call item_list --domain-id dom_xyz
```

### Busca avançada
```bash
# Busca em workspace específico
mcp call item_search --query "spring" --workspace-id ws_abc

# Busca em domain específico
mcp call item_search --query "controller" --domain-id dom_xyz

# Busca por tipo
mcp call item_list --workspace-id ws_abc --type rule
```

### Metadata & Acessos
```bash
# Item com metadata completa
mcp call item_get --item-id item_abc
# Retorna: title, type, memory_class, tags, labels, relations, access_count, last_accessed

# Promover memória (ephemeral → longterm)
mcp call memory_promote --item-id item_abc --new-class longterm
```

---

## Troubleshooting

| Problema | Solução |
|----------|---------|
| "Connection not found" | Rodar `connection_list` pra ver disponíveis |
| "Workspace not found" | Usar `workspace_list` pra obter IDs corretos |
| "Cannot connect to PostgreSQL" | Rodar `connection_test --connection-id postgres` |
| Item search lento | Checar índices com `connection_test_detailed` |
| Migration falha | Garantir target DB vazio, rodar `connection_init_db` antes |

---

## Próximos Passos (v0.2+)

- [ ] Permissionamento (read/write por usuario)
- [ ] Workflow editorial (draft → review → approved)
- [ ] Real-time collaboration (WebSocket)
- [ ] Knowledge graph visualization
- [ ] Mobile app

---
```

---

## 4. Update Tool Registration (`src/main.py`)

Ao registrar cada tool, incluir a description completa:

```python
def register_all_tools():
    """Registra todos os 44 MCP tools com descriptions."""
    
    # Connection (6 + 6 = 12)
    mcp.register_tool(connection_list)
    mcp.register_tool(connection_create)
    mcp.register_tool(connection_get)
    mcp.register_tool(connection_delete)
    mcp.register_tool(connection_test)
    mcp.register_tool(connection_init_db)    # T9
    mcp.register_tool(migrate_workspaces)    # T9
    
    # Workspace (5)
    mcp.register_tool(workspace_create)
    mcp.register_tool(workspace_list)
    mcp.register_tool(workspace_get)
    mcp.register_tool(workspace_delete)
    mcp.register_tool(workspace_export)
    
    # Domain (4)
    mcp.register_tool(domain_create)
    mcp.register_tool(domain_list)
    mcp.register_tool(domain_get)
    mcp.register_tool(domain_delete)
    
    # Item (7)
    mcp.register_tool(item_create)
    mcp.register_tool(item_list)
    mcp.register_tool(item_get)
    mcp.register_tool(item_update)
    mcp.register_tool(item_delete)
    mcp.register_tool(item_search)
    # ... mais item tools
    
    # ... resto dos tools
    
    return count_registered_tools()
```

---

## Critério de Sucesso (T10)

✓ `src/mcp/INSTRUCTIONS.md` criado (system prompt claro)  
✓ Todos os 44 tools têm descrição melhorada (Use when, Returns, Example, Notes)  
✓ `docs/MCP_USAGE.md` com 4 workflows práticos  
✓ Nenhuma redundância entre os 3 docs  
✓ Agente consegue usar MCP intuitivamente sem pedir help  
✓ Documentação integrada em `src/main.py` (help texts)  

---

## Timeline

- System Prompt: 1h
- Melhorar 44 tool descriptions: 1h
- README workflows + troubleshooting: 1h

**Total: 3 horas**

---

## Post-T10

Depois disso:
- T9 + T10 completam
- Integrar T7 + T8a + T9 + T10 + T6
- Tag v0.1.0
- Despachar T8 (React UI)
