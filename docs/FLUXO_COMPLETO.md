# Fluxo Completo — MCP Knowledge OS

Este documento mostra um fluxo completo end-to-end: criar workspace, domain, items, buscar, exportar.

## Setup

```bash
# Crie virtualenv e instale
python -m venv venv
source venv/bin/activate  # ou .\venv\Scripts\Activate.ps1 no Windows
pip install -e ".[dev]"

# Bootstrap do banco
python src/main.py --bootstrap

# Verifique
python src/main.py --check-db
# Output: {"status": "ok", "database": "connected"}
```

## Fluxo Exemplo: Workspace BTG

### 1. Criar Workspace

```python
# Cliente MCP chama:
workspace_create({
  "name": "BTG",
  "description": "Workspace principal — projetos BTG"
})

# Resposta:
# {
#   "id": "ws_001",
#   "name": "BTG",
#   "description": "Workspace principal — projetos BTG",
#   "created_at": "2026-10-02T16:30:00Z",
#   "updated_at": "2026-10-02T16:30:00Z"
# }
```

### 2. Criar Domain

```python
domain_create({
  "workspace": "BTG",
  "name": "Orquestra 2.0",
  "description": "Projeto de orquestração"
})

# Resposta:
# {
#   "id": "dm_001",
#   "workspace_id": "ws_001",
#   "name": "Orquestra 2.0",
#   "description": "Projeto de orquestração",
#   "created_at": "2026-10-02T16:30:10Z",
#   "updated_at": "2026-10-02T16:30:10Z"
# }
```

### 3. Criar Items (Conhecimento)

```python
# Item 1: Knowledge — fato aprendido
item_create({
  "workspace": "BTG",
  "domain": "Orquestra 2.0",
  "type": "knowledge",
  "memory_class": "longterm",
  "title": "ConditionalOnProperty não é dinâmico",
  "summary": "Spring: ConditionalOnProperty avalia em tempo de inicialização, não em runtime.",
  "content": """
  A anotação @ConditionalOnProperty não permite condições dinâmicas.
  
  ❌ Errado:
  @ConditionalOnProperty(name="feature.enabled", havingValue="true")
  public SomeService someService() { ... }  // Cria sempre ou nunca
  
  ✅ Correto:
  @ConditionalOnProperty(name="feature.enabled", havingValue="true")
  @Bean
  public SomeService someService() { ... }  // Decidido em startup
  
  Se precisar dinâmico: use @Conditional customizado com ConditionContext.
  """,
  "tags": ["spring", "java", "conditional"],
  "labels": ["official"],
  "confidence": 95,
  "importance": 8,
  "ttl_days": None  # longterm = sem expiração
})
```

```python
# Item 2: Rule — diretriz
item_create({
  "workspace": "BTG",
  "domain": "Orquestra 2.0",
  "type": "rule",
  "memory_class": "canonical",
  "title": "Sempre validar entrada de usuário",
  "summary": "Nenhuma requisição externa chega direto na lógica sem validação.",
  "content": """
  Validação em três níveis:
  1. Boundary: validação estrutural (Pydantic, JPA validators)
  2. Business: validação de regras (CustomValidator)
  3. Security: rate limit, sanitização (WAF, middleware)
  """,
  "tags": ["security", "validation"],
  "labels": ["critical"],
  "confidence": 100,
  "importance": 10,
  "ttl_days": None  # canonical = nunca expira
})
```

```python
# Item 3: Procedure — passo a passo
item_create({
  "workspace": "BTG",
  "domain": "Orquestra 2.0",
  "type": "procedure",
  "memory_class": "longterm",
  "title": "Deploy Orquestra 2.0",
  "summary": "Fluxo de deploy: build → test → push → deploy",
  "content": """
  ## Pré-requisitos
  - Acesso ao Registry (ECR)
  - Kubeconfig configurado
  - Helm instalado
  
  ## Passos
  1. Build local: `make build`
  2. Testes: `make test` (deve passar 100%)
  3. Push image: `make push`
  4. Deploy: `helm upgrade --install orquestra ./helm`
  5. Verificar: `kubectl rollout status deployment/orquestra`
  
  ## Rollback
  `helm rollback orquestra 1` (volta para release anterior)
  """,
  "tags": ["deploy", "kubernetes", "helm"],
  "labels": ["official"],
  "confidence": 90,
  "importance": 9,
  "ttl_days": None
})
```

### 4. Buscar Conhecimento

```python
# Busca por palavra-chave
item_search({
  "workspace": "BTG",
  "domain": "Orquestra 2.0",
  "query": "ConditionalOnProperty",
  "types": ["knowledge"],
  "memory_classes": ["longterm", "canonical"],
  "limit": 10
})

# Resposta (SEM content):
# [
#   {
#     "id": "it_001",
#     "title": "ConditionalOnProperty não é dinâmico",
#     "summary": "Spring: ConditionalOnProperty avalia em tempo de inicialização...",
#     "score": 98
#   }
# ]
```

```python
# Busca mais ampla
item_search({
  "workspace": "BTG",
  "query": "spring java",
  "limit": 20
})

# Resposta: todos os items em BTG que mencionem "spring" ou "java" (FTS5)
```

### 5. Obter Item Completo

```python
item_get({
  "id": "it_001"
})

# Resposta (COM content):
# {
#   "id": "it_001",
#   "workspace_id": "ws_001",
#   "domain_id": "dm_001",
#   "type": "knowledge",
#   "memory_class": "longterm",
#   "title": "ConditionalOnProperty não é dinâmico",
#   "summary": "Spring: ConditionalOnProperty avalia em tempo de inicialização...",
#   "content": "A anotação @ConditionalOnProperty...",  # ← AQUI está o content completo
#   "tags": ["spring", "java", "conditional"],
#   "labels": ["official"],
#   "confidence": 95,
#   "importance": 8,
#   "created_at": "2026-10-02T16:31:00Z",
#   "updated_at": "2026-10-02T16:31:00Z",
#   "last_accessed": "2026-10-02T16:32:00Z",
#   "access_count": 5
# }
```

### 6. Criar Relações entre Items

```python
relation_create({
  "source_id": "it_001",  # ConditionalOnProperty
  "target_id": "it_002",  # Sempre validar entrada
  "relation_type": "related_to"
})

# Tipo de relações: related_to, depends_on, implements, references, supersedes, derived_from
```

### 7. Listar Relações

```python
relation_list({
  "item_id": "it_001"
})

# Resposta:
# [
#   {
#     "id": "rel_001",
#     "source_item_id": "it_001",
#     "target_item_id": "it_002",
#     "relation_type": "related_to"
#   }
# ]
```

### 8. Promover Item para Canonical

```python
memory_promote({
  "item_id": "it_002",
  "target_memory": "canonical"
})

# Resposta: Item com memory_class="canonical" (agora é oficial)
```

### 9. Exportar Workspace

```python
workspace_export({
  "name": "BTG"
})

# Retorna: workspace-btg.zip (100 KB)
```

**Conteúdo do ZIP:**
```
workspace-btg.zip
├── manifest.json          # Metadados (versão, timestamp)
├── workspace.json         # Definição do workspace
├── domains/
│   └── orquestra-2.0.json
├── items/
│   ├── it_001.json        # ConditionalOnProperty
│   ├── it_002.json        # Sempre validar entrada
│   └── it_003.json        # Deploy Orquestra
├── artifacts/
│   ├── helm-values-yaml   # Se houver
│   └── dockerfile-txt
└── relations/
    └── relations.json      # Todas as relações
```

### 10. Importar Workspace em Novo Projeto

```python
workspace_import({
  "file_path": "/exports/workspace-btg.zip"
})

# Restaura:
# - Nova workspace "BTG" com novo ID
# - Todos os domains com novo ID
# - Todos os items com novo ID (mantém semântica)
# - Tags + labels
# - Relações (source_id, target_id atualizados)
# - Artifacts (copiam binários)
```

## Casos de Uso

### Use Case 1: Migrar Knowledge de Claude.md para Knowledge OS

1. Leia `CLAUDE.md` existente
2. Crie items com `type="rule"` e `memory_class="canonical"`
3. Organize por domains (ex: "Auth", "API", "Deployment")
4. Busque com agentes Claude usando `item_search` em vez de ler arquivo

### Use Case 2: Onboard Novo Dev em Projeto

1. Dev acessa workspace do projeto
2. Busca por `query="padrão"` → encontra patterns
3. Busca por `query="como fazer"` → encontra procedures
4. Busca por `type="rule"` → vê regras do projeto

### Use Case 3: Documentação Operacional Viva

1. Crie items com `type="procedure"` e `memory_class="longterm"`
2. Quando fizer operação fora do script, atualize o item
3. Agentes sempre consultam a versão atual

### Use Case 4: Ephemeral Knowledge (Contexto Temporário)

1. Crie item com `memory_class="ephemeral"` e `ttl_days=7`
2. Item expira automaticamente em 7 dias (cleanup cron)
3. Adequado para: "temos downtime sexta-feira", "lib X tem bug conhecido"

## Performance

**Benchmark esperado:**
- Criar item: < 50ms
- Buscar (FTS5): < 100ms (1000 items)
- Exportar workspace: < 1s (500 items + artifacts)
- RAM usage: < 100MB (em uso)

## Próximos Passos

- [ ] Integrar em Claude Code como MCP nativo
- [ ] CLI: `knowledge-mcp query "..."` 
- [ ] Web UI: browse workspaces, search, create
- [ ] Sync com Git (backup automático de exports)
