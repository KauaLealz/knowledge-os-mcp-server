# MCP Knowledge OS

> Servidor MCP local que funciona como a fonte única de conhecimento para agentes Claude.

Substitui: `.cursor/rules`, `CLAUDE.md`, `AGENTS.md`, runbooks, notas pessoais, snippets, skills customizadas e documentação operacional.

## Princípios

- **Local-first**: Nenhuma dependência de serviços externos
- **SQLite criptografado**: AES-256 com SQLCipher (opcional)
- **Pouquíssimo RAM**: Adequado para agentes em lotes
- **Curadoria humana**: Agente responsável, MCP apenas persiste
- **Sem embeddings**: Sem LLM interno, sem classificação automática

## Stack

| Componente | Tecnologia |
|---|---|
| Runtime | Python 3.12+ |
| MCP Framework | FastMCP |
| Banco de dados | SQLite + FTS5 |
| Criptografia | SQLCipher (opcional) |
| ORM | SQLAlchemy 2.x |
| Schemas | Pydantic v2 |

## Instalação

### Pré-requisitos
- Python 3.12+
- pip ou uv

### Setup

```bash
# Clone ou entre no diretório
cd knowledge-mcp

# Crie virtualenv
python -m venv venv
source venv/bin/activate  # Linux/macOS
# ou
.\venv\Scripts\Activate.ps1  # Windows PowerShell

# Instale dependências
pip install -e ".[dev]"

# Configure variáveis de ambiente (opcional)
cp .env.example .env
# Edite .env conforme necessário

# Bootstrap do banco (cria tabelas, labels padrão)
python src/main.py --bootstrap

# Verifique conexão
python src/main.py --check-db
```

## Uso

### Iniciar Servidor MCP

```bash
python src/main.py
```

O servidor estará disponível via STDIO (padrão para MCP).

### Exemplo de Fluxo Completo

```python
# Cliente MCP pode chamar ferramentas:

# 1. Criar workspace
workspace_create({
  "name": "BTG",
  "description": "Workspace principal"
})

# 2. Criar domain
domain_create({
  "workspace": "BTG",
  "name": "Orquestra 2.0"
})

# 3. Criar item (conhecimento)
item_create({
  "workspace": "BTG",
  "domain": "Orquestra 2.0",
  "type": "knowledge",
  "memory_class": "longterm",
  "title": "ConditionalOnProperty",
  "summary": "Não permite criação dinâmica de beans.",
  "content": "Detalhamento completo...",
  "tags": ["spring", "java"],
  "labels": ["official"],
  "confidence": 90,
  "importance": 5
})

# 4. Buscar conhecimento
item_search({
  "workspace": "BTG",
  "query": "ConditionalOnProperty",
  "types": ["knowledge"],
  "limit": 10
})
# Retorna: [{id, title, summary, score}, ...]

# 5. Obter item completo
item_get({
  "id": "..."
})
# Retorna: {id, title, summary, content, tags, labels, ...}
```

## Modelo Conceitual

```
Workspace (grande contexto)
└── Domain (projeto/assunto)
    └── Item (conhecimento)
    └── Item (regra)
    └── Item (procedure)
```

**Exemplo:**
```
BTG
├── Orquestra 2.0
│   ├── Regra: Java 21 sempre
│   └── Procedure: Deploy
├── OpenSearch
└── Kubernetes

Personal
├── Cursor (rules, patterns)
├── MCP (arquitetura)
└── Homelab (runbooks)
```

## Item Types

| Tipo | Propósito |
|---|---|
| `context` | Descreve ambiente (arquitetura, stack, limitações) |
| `rule` | Substitui .cursor/rules, Claude Rules |
| `pattern` | Padrões recorrentes (Hexagonal Arch, MCP Pattern) |
| `procedure` | Passo a passo (Deploy, rollback, provisioning) |
| `knowledge` | Fatos aprendidos |
| `insight` | Observações e tradeoffs |
| `artifact` | Arquivos reutilizáveis (JSON, YAML, Helm) |

## Classes de Memória

| Classe | TTL | Propósito |
|---|---|---|
| `ephemeral` | Obrigatório (7, 15, 30 dias) | Curto prazo, expiração automática |
| `working` | Opcional | Em validação |
| `longterm` | Nenhum | Persistente |
| `canonical` | Nenhum | Oficial, promovido explicitamente |

## Ferramentas MCP (19 total)

### Workspace (6)
- `workspace_create`, `workspace_list`, `workspace_get`, `workspace_delete`, `workspace_export`, `workspace_import`

### Domain (6)
- `domain_create`, `domain_list`, `domain_get`, `domain_delete`, `domain_export`, `domain_import`

### Item (5) — Core
- `item_create`, `item_update`, `item_delete`, `item_get`, `item_search` (principal)

### Relation (3)
- `relation_create`, `relation_list`, `relation_delete`

### Memory (2)
- `memory_promote`, `memory_renew`

### Tag (3)
- `tag_create`, `tag_list`, `tag_delete`

### Artifact (3)
- `artifact_attach`, `artifact_list`, `artifact_get`

## Otimizações para Agentes

1. **item_search sempre retorna `summary`** (nunca `content` por padrão)
2. **item_get retorna conteúdo completo**
3. **Ordenação padrão**: importance desc, confidence desc, access_count desc, updated_at desc
4. **Filtros aceitos**: workspace, domain, type, memory_class, tags, labels

## Segurança

### Variáveis de Ambiente

```bash
# Obrigatório
MCP_DB_PATH=./database/knowledge.db

# Opcional: criptografia AES-256
MCP_DB_KEY=seu_hash_de_32_caracteres_aqui
```

### Sem Chave (SQLite simples)
```bash
# Banco fica em plain-text na pasta database/
# Adequado para desenvolvimento local
MCP_DB_PATH=./database/knowledge.db
```

### Com Chave (SQLCipher)
```bash
# Criptografia AES-256
export MCP_DB_KEY=$(openssl rand -base64 32)
python src/main.py
```

## Arquitetura

```
src/
├── main.py
│   └── FastMCP server, registra tools
├── config.py
│   └── Carrega MCP_DB_PATH, MCP_DB_KEY, valida
├── db/
│   ├── models.py
│   │   └── 8 modelos SQLAlchemy
│   ├── session.py
│   │   └── Engine init, session factory, WAL mode, FTS5
│   └── migrations.py
│       └── Bootstrap: cria labels padrão
├── services/
│   ├── workspace_service.py
│   ├── domain_service.py
│   ├── item_service.py
│   ├── relation_service.py
│   ├── memory_service.py
│   ├── import_export_service.py
│   └── tag_service.py
├── mcp/
│   ├── workspace_tools.py
│   ├── domain_tools.py
│   ├── item_tools.py
│   ├── relation_tools.py
│   ├── memory_tools.py
│   ├── tag_tools.py
│   └── artifact_tools.py
└── schemas/
    └── Pydantic validators
```

## Testes

```bash
# Rodar testes
pytest -v

# Com cobertura
pytest --cov=src -v

# Apenas um arquivo
pytest tests/test_item_tools.py -v
```

## Export/Import

### Export Workspace
```python
workspace_export({
  "name": "BTG"
})
# Retorna: workspace-btg.zip
```

Estrutura do ZIP:
```
manifest.json      # Metadados
workspace.json     # Definição do workspace
domains/           # Estrutura de domains
items/             # Items em JSON
artifacts/         # Binários anexados
relations/         # Relações entre items
```

### Import Workspace
```python
workspace_import({
  "file_path": "./exports/workspace-btg.zip"
})
# Restaura estrutura completa
```

## Roadmap

- [ ] v0.1 (em progresso): MVP core — workspace, domain, item, search, export/import
- [ ] v0.2: Cron job para memory_cleanup (ephemeral expirados)
- [ ] v0.3: Web UI simples (browse, search, create)
- [ ] v0.4: CLI (`knowledge-mcp` command)
- [ ] v0.5: Integração com Claude Code (instalação automática)

## Suporte

- Docs: veja `docs/` para exemplos e guias
- Issues: crie no repositório
- Discussões: veja Discussions

## Licença

MIT
