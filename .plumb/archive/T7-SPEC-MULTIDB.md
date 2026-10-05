# T7 Spec: Multi-Connection + Multi-Database Support

## Objetivo

Criar camada de **Connection** acima de Workspace, permitindo:
- Uma **Connection** pode ter **N Workspaces**
- Uma **Connection** aponta para um banco de dados específico (SQLite, MySQL, PostgreSQL)
- Suportar múltiplas conexões simultâneas (locais ou remotas)

## Modelo Conceitual Novo

```
Connection (ponto de acesso a um banco)
├── type: sqlite | mysql | postgresql
├── url: sqlite:///path/db.db | mysql://... | postgresql://...
├── metadata: host, port, database, username (criptografado)
└── Workspace N (dentro dessa conexão)
    ├── Domain
    └── Item
```

**Exemplo:**
```
Connection "BTG Local" (sqlite:///./database/btg.db)
├── Workspace "Orquestra 2.0"
│   └── Domain, Items
├── Workspace "OpenSearch"
└── Workspace "Kubernetes"

Connection "Company Server" (postgresql://prod.company.com/knowledge)
├── Workspace "Shared"
└── Workspace "Archive"

Connection "MyPC MySQL" (mysql://localhost/personal)
└── Workspace "Personal"
```

## Alterações no Schema

### Novo Modelo: Connection

```python
class Connection(Base):
    """Representa uma conexão a um banco de dados."""
    __tablename__ = "connections"
    
    id = Column(String(36), primary_key=True)
    name = Column(String(255), unique=True, nullable=False)  # "BTG Local", "Company Server"
    
    # Database info
    db_type = Column(String(20), nullable=False)  # sqlite, mysql, postgresql
    db_url = Column(String(2048), nullable=False)  # sqlite:///..., mysql://..., etc
    
    # Metadata (para exibição)
    host = Column(String(255), nullable=True)  # localhost, prod.company.com
    port = Column(Integer, nullable=True)  # 3306 (MySQL), 5432 (PostgreSQL)
    database = Column(String(255), nullable=True)  # knowledge, btg_db
    username = Column(String(255), nullable=True)  # root, postgres (não criptografado)
    
    # Status
    is_active = Column(Boolean, default=True)
    last_tested = Column(DateTime, nullable=True)
    test_result = Column(String(500), nullable=True)  # "connected", "connection failed"
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    workspaces = relationship("Workspace", back_populates="connection", cascade="all, delete-orphan")
```

### Alteração: Workspace

```python
class Workspace(Base):
    __tablename__ = "workspaces"
    
    id = Column(String(36), primary_key=True)
    
    # NOVO: referência à connection
    connection_id = Column(String(36), ForeignKey("connections.id"), nullable=False)
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ALTERADO: unique constraint
    __table_args__ = (
        UniqueConstraint("connection_id", "name", name="uq_workspace_connection_name"),
        Index("idx_workspace_connection", "connection_id"),
    )
    
    # Novo relacionamento
    connection = relationship("Connection", back_populates="workspaces")
    domains = relationship("Domain", back_populates="workspace", cascade="all, delete-orphan")
    items = relationship("Item", back_populates="workspace", cascade="all, delete-orphan")
```

## Arquitetura do Código

```
src/
├── db/
│   ├── session.py (REFATORADO)
│   │   - ConnectionManager (novo): gerencia engines por connection_id
│   │   - get_engine(connection_id) → Engine
│   │   - get_session(connection_id) → Session
│   ├── dialects/
│   │   ├── __init__.py
│   │   ├── base.py (ABC DatabaseDialect)
│   │   ├── sqlite.py (SQLiteDialect)
│   │   ├── mysql.py (MySQLDialect + FTS fallback)
│   │   └── postgresql.py (PostgreSQLDialect + tsvector)
│   └── models.py
│       - Adicionar Connection
│       - Modificar Workspace (adicionar connection_id)
│
├── services/
│   ├── connection_service.py (NOVO)
│   │   - ConnectionService(create, list, get, delete, test, update)
│   ├── workspace_service.py (REFATORADO)
│   │   - WorkspaceService(connection_id) — sempre com context de connection
│   ├── ... (outros services — idênticos, mas recebem connection_id)
│
├── mcp/
│   ├── connection_tools.py (NOVO)
│   │   - connection_create, connection_list, connection_get, connection_delete, connection_test
│   ├── workspace_tools.py (REFATORADO)
│   │   - Todos os tools recebem connection_id
│   ├── ... (outros tools — sem mudanças visíveis)
│
├── config.py (REFATORADO)
│   - ConnectionManager em lugar de global engine
│   - Suporte a N connection URLs
│   - Detecção automática de dialect (sqlite/mysql/postgresql)
│
└── main.py
    - register_all_tools() adiciona connection_tools
    - Middleware para resolver connection_id do request
```

## Ferramentas MCP Novas (Connection)

```python
@mcp.tool()
def connection_create(
    name: str,
    db_type: str,  # "sqlite", "mysql", "postgresql"
    url: str,      # "sqlite:///./db.db", "mysql://user:pass@host/db", etc
    test: bool = True,  # testa conexão antes de salvar
) -> dict:
    """Cria nova conexão a um banco de dados."""
    # Valida URL, testa conexão, cria registro

@mcp.tool()
def connection_list() -> list[dict]:
    """Lista todas as conexões."""

@mcp.tool()
def connection_get(connection_id: str) -> dict:
    """Detém conexão por ID."""
    # Retorna: name, db_type, host, port, database, is_active, last_tested

@mcp.tool()
def connection_delete(connection_id: str) -> dict:
    """Deleta conexão (cascata: deleta workspaces)."""

@mcp.tool()
def connection_test(connection_id: str) -> dict:
    """Testa conexão (conecta, cria tabela dummy, deleta)."""
    # Retorna: status, message, latency_ms

@mcp.tool()
def connection_update(
    connection_id: str,
    name: str = None,
    is_active: bool = None,
) -> dict:
    """Atualiza metadados da conexão."""
```

## Suporte a DBs

### SQLite (já suportado)
```python
class SQLiteDialect(DatabaseDialect):
    def create_engine(url: str) -> Engine:
        # sqlite:///./database/mydb.db
        return create_engine(url, ...)
    
    def supports_fts() -> bool:
        return True  # FTS5 nativo
```

### MySQL (novo)
```python
class MySQLDialect(DatabaseDialect):
    def create_engine(url: str) -> Engine:
        # mysql+pymysql://root:password@localhost/knowledge
        return create_engine(url, ...)
    
    def supports_fts() -> bool:
        return False  # MySQL < 8.0 não tem FTS, fallback para LIKE
    
    def create_fts_table():
        # Fallback: usar FULLTEXT INDEX ou simular com LIKE
        # Ou usar Sphinx/Elasticsearch externamente
```

### PostgreSQL (novo)
```python
class PostgreSQLDialect(DatabaseDialect):
    def create_engine(url: str) -> Engine:
        # postgresql+psycopg://user:password@localhost/knowledge
        return create_engine(url, ...)
    
    def supports_fts() -> bool:
        return True  # tsvector nativo
    
    def create_fts_table():
        # CREATE EXTENSION pg_trgm;
        # CREATE INDEX items_fts_idx ON items USING gin(
        #   to_tsvector('portuguese', title || ' ' || summary || ' ' || content)
        # );
```

## Migração de Dados (SQLite → PostgreSQL)

```python
class MigrationService:
    def migrate_sqlite_to_postgresql(
        sqlite_path: str,
        postgresql_url: str,
    ) -> dict:
        """
        Lê todos os workspaces, domains, items, relations, artifacts de SQLite
        Escreve em PostgreSQL novo
        Retorna: {workspaces_migrated, items_migrated, artifacts_copied, errors}
        """
        # 1. Conectar em SQLite (read-only)
        # 2. Conectar em PostgreSQL (init_db)
        # 3. Para cada workspace:
        #    a. Copiar domains
        #    b. Copiar items (sem content em stream)
        #    c. Copiar relations
        #    d. Copiar artifacts (ler do disco, escrever em PostgreSQL)
        # 4. Validar contagem
```

## Novo Fluxo (Exemplo)

```
MCP Client:

1. connection_create({
    "name": "PostgreSQL Prod",
    "db_type": "postgresql",
    "url": "postgresql://user:pass@prod.company.com:5432/knowledge"
   })
   → Status: "tested, ok"

2. workspace_create({
    "connection_id": "conn_123",
    "name": "Shared Knowledge",
    "description": "Conhecimento compartilhado da equipe"
   })
   → Cria workspace em PostgreSQL prod

3. domain_create({
    "connection_id": "conn_123",
    "workspace": "Shared Knowledge",
    "name": "DevOps",
    "description": "Procedimentos e conhecimentos de DevOps"
   })
   → Cria domain em PostgreSQL

4. item_search({
    "connection_id": "conn_123",
    "workspace": "Shared Knowledge",
    "query": "kubernetes"
   })
   → Busca FTS5/tsvector em PostgreSQL
```

## Testes (T7)

```python
# tests/test_connections.py
- test_connection_create_sqlite
- test_connection_create_mysql
- test_connection_create_postgresql
- test_connection_test (valida cada tipo)
- test_connection_delete_cascade
- test_workspace_in_connection

# tests/test_dialects.py
- test_sqlite_fts
- test_postgresql_fts
- test_mysql_fallback

# tests/test_migration.py
- test_migrate_sqlite_to_postgresql
- test_migrate_preserves_data
- test_migrate_validates_counts

# tests/test_multidb.py
- test_multiple_connections_isolated
- test_workspace_only_sees_own_connection
- test_tools_with_connection_id
```

## Critério de Sucesso (T7)

✓ `pytest tests/ -v` → 130+ testes passed (104 + 30 novos)
✓ 3 bancos funcionando (SQLite, MySQL, PostgreSQL)
✓ Connection CRUD completo
✓ Workspace isolado por connection
✓ Migration SQLite → PostgreSQL validada
✓ `ruff check` clean
✓ Zero breaking changes com T1-T5 (backward compatible)

## Timeline

**T6:** Roda em paralelo (finaliza testes + docs)
**T7:** Paralelo com T6 (implementa multi-db + connection)
**Merge:** Após T6 + T7 completarem
**Status:** v0.1 + multi-db support integrado

---

**Próximo:** Despachar T7 enquanto T6 finaliza
