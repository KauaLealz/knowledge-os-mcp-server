# T9 Spec Final: Connection Config + 2 Tools

## Objetivo

Implementar **sistema de configuração robusto** para gerenciar conexões (SQLite local, PostgreSQL, MySQL) com **2 modos:**
- **Simples:** Auto-cria `.knowledge/connections.json` com SQLite default (plug & play)
- **Avançado:** Multi-conexões via config file (editar JSON)

**Total:** 2 MCP tools novos + Config loader + Pydantic validation

---

## 1. Config File (`.knowledge/connections.json`)

### Estrutura

```json
{
  "version": "1.0",
  "default": "sqlite_local",
  "connections": [
    {
      "id": "sqlite_local",
      "name": "Local SQLite",
      "db_type": "sqlite",
      "path": "./knowledge.db",
      "enabled": true,
      "created_at": "2026-10-02T14:00:00Z"
    },
    {
      "id": "postgres_prod",
      "name": "PostgreSQL Production",
      "db_type": "postgresql",
      "host": "prod.company.com",
      "port": 5432,
      "database": "knowledge_db",
      "username": "dbuser",
      "password_env": "POSTGRES_PASSWORD",
      "enabled": true,
      "created_at": "2026-10-02T15:00:00Z"
    },
    {
      "id": "mysql_local",
      "name": "MySQL Local Dev",
      "db_type": "mysql",
      "host": "localhost",
      "port": 3306,
      "database": "knowledge",
      "username": "root",
      "password_env": "MYSQL_PASSWORD",
      "enabled": false,
      "created_at": "2026-10-02T16:00:00Z"
    }
  ]
}
```

### Validação (Pydantic)

```python
# src/config.py

from pydantic import BaseModel, field_validator
from typing import Literal
from datetime import datetime

class ConnectionConfig(BaseModel):
    """Uma conexão individual (SQLite, PostgreSQL ou MySQL)."""
    
    id: str  # "sqlite_local", "postgres_prod"
    name: str  # "Local SQLite", "PostgreSQL Production"
    db_type: Literal["sqlite", "postgresql", "mysql"]
    
    # SQLite
    path: str | None = None  # "./knowledge.db"
    
    # PostgreSQL / MySQL
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password_env: str | None = None  # "POSTGRES_PASSWORD" → carrega do .env
    
    enabled: bool = True
    created_at: datetime | None = None
    
    @field_validator("id")
    @classmethod
    def id_valid(cls, v):
        import re
        if not re.match(r"^[a-z0-9_-]+$", v):
            raise ValueError("ID must be lowercase alphanumeric with hyphens/underscores")
        return v
    
    @field_validator("port")
    @classmethod
    def port_valid(cls, v):
        if v and not (1 <= v <= 65535):
            raise ValueError("Port must be 1-65535")
        return v
    
    def get_url(self) -> str:
        """Retorna URL de conexão (com senha do .env se aplicável)."""
        if self.db_type == "sqlite":
            return f"sqlite:///{self.path}"
        
        password = ""
        if self.password_env:
            password = os.getenv(self.password_env, "")
            if password:
                password = f":{password}@"
        
        if self.db_type == "postgresql":
            return f"postgresql://{self.username}{password}{self.host}:{self.port}/{self.database}"
        elif self.db_type == "mysql":
            return f"mysql+pymysql://{self.username}{password}{self.host}:{self.port}/{self.database}"


class ConnectionsFile(BaseModel):
    """Arquivo de configuração de conexões."""
    
    version: str = "1.0"
    default: str  # ID da conexão padrão
    connections: list[ConnectionConfig]
    
    @field_validator("default")
    @classmethod
    def default_exists(cls, v, info):
        if "connections" in info.data:
            ids = [c.id for c in info.data["connections"]]
            if v not in ids:
                raise ValueError(f"Default connection '{v}' not found in connections list")
        return v
    
    def get_connection(self, connection_id: str) -> ConnectionConfig:
        """Retorna uma conexão por ID."""
        for conn in self.connections:
            if conn.id == connection_id:
                return conn
        raise ValueError(f"Connection '{connection_id}' not found")
    
    def get_default_connection(self) -> ConnectionConfig:
        """Retorna a conexão padrão."""
        return self.get_connection(self.default)
```

---

## 2. Config Loader (Modo Simples + Avançado)

```python
# src/config.py

class ConfigManager:
    """Gerencia conexões: carrega, valida, cria defaults."""
    
    CONNECTIONS_FILE = Path(".knowledge/connections.json")
    
    @staticmethod
    def create_default_config() -> ConnectionsFile:
        """Cria config padrão (SQLite local)."""
        return ConnectionsFile(
            version="1.0",
            default="sqlite_local",
            connections=[
                ConnectionConfig(
                    id="sqlite_local",
                    name="Local SQLite",
                    db_type="sqlite",
                    path="./knowledge.db",
                    enabled=True,
                    created_at=datetime.now(timezone.utc)
                )
            ]
        )
    
    @staticmethod
    def load_or_create() -> ConnectionsFile:
        """Carrega config ou cria default se não existir."""
        if ConfigManager.CONNECTIONS_FILE.exists():
            with open(ConfigManager.CONNECTIONS_FILE) as f:
                data = json.load(f)
                return ConnectionsFile(**data)
        else:
            # Modo Simples: cria default
            config = ConfigManager.create_default_config()
            ConfigManager.save(config)
            return config
    
    @staticmethod
    def save(config: ConnectionsFile) -> None:
        """Salva config em arquivo."""
        Path(".knowledge").mkdir(parents=True, exist_ok=True)
        with open(ConfigManager.CONNECTIONS_FILE, "w") as f:
            json.dump(config.model_dump(mode="json"), f, indent=2)
    
    @staticmethod
    def validate_connection(conn: ConnectionConfig) -> dict:
        """Valida uma conexão (tenta conectar)."""
        try:
            engine = create_engine(conn.get_url())
            with engine.connect() as connection:
                # Query simples (dialect-specific)
                if conn.db_type == "sqlite":
                    connection.execute(text("SELECT 1"))
                else:
                    connection.execute(text("SELECT 1 as ok"))
            engine.dispose()
            return {"status": "ok", "message": "Connection successful"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
```

---

## 3. MCP Tools (2)

### Tool 1: `connection_init_db`

```python
@mcp.tool()
def connection_init_db(connection_id: str) -> dict:
    """
    Inicializa schema em uma conexão.
    
    Use case: Depois de criar uma nova connection, prepara o banco.
    - SQLite: cria arquivo + schema se não existir
    - PostgreSQL/MySQL: cria schema se vazio
    """
    try:
        config = ConfigManager.load_or_create()
        conn = config.get_connection(connection_id)
        
        # Verificar se conexão é acessível
        validation = ConfigManager.validate_connection(conn)
        if validation["status"] != "ok":
            return {
                "connection_id": connection_id,
                "status": "error",
                "message": f"Cannot connect: {validation['message']}"
            }
        
        # Obter engine e inicializar schema
        engine = get_engine(connection_id)
        from src.db.models import Base
        
        # Criar tabelas (idempotente)
        Base.metadata.create_all(engine)
        
        # Se SQLite, criar índices FTS5
        if conn.db_type == "sqlite":
            from src.db.migrations import _create_fts5_triggers
            _create_fts5_triggers(engine)
        
        # Se PostgreSQL, criar extensões
        elif conn.db_type == "postgresql":
            with engine.connect() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                connection.commit()
        
        return {
            "connection_id": connection_id,
            "status": "initialized",
            "db_type": conn.db_type,
            "message": "Database schema initialized successfully"
        }
    
    except ValueError as e:
        return {"connection_id": connection_id, "status": "error", "message": str(e)}
    except Exception as e:
        return {"connection_id": connection_id, "status": "error", "message": str(e)}


@mcp.tool()
def migrate_workspaces(
    from_connection_id: str,
    to_connection_id: str,
    mode: str = "replace"
) -> dict:
    """
    Migra workspaces entre conexões.
    
    Modes:
    - "replace": limpa destino, copia tudo da origem
    - "merge": mistura (tags/labels por nome, workspaces/items novos)
    
    Use case: Mover dados de SQLite local pra PostgreSQL produção.
    """
    try:
        config = ConfigManager.load_or_create()
        
        # Validar conexões
        from_conn = config.get_connection(from_connection_id)
        to_conn = config.get_connection(to_connection_id)
        
        if not from_conn.enabled:
            return {"status": "error", "message": f"Source connection '{from_connection_id}' is disabled"}
        if not to_conn.enabled:
            return {"status": "error", "message": f"Target connection '{to_connection_id}' is disabled"}
        
        # Validar conectividade
        for conn_id, conn in [(from_connection_id, from_conn), (to_connection_id, to_conn)]:
            val = ConfigManager.validate_connection(conn)
            if val["status"] != "ok":
                return {"status": "error", "message": f"Cannot connect to '{conn_id}': {val['message']}"}
        
        # Executar migração
        from src.services.migration_service import MigrationService
        service = MigrationService(
            from_engine=get_engine(from_connection_id),
            to_engine=get_engine(to_connection_id)
        )
        
        result = service.migrate(mode=mode)
        
        return {
            "from_connection": from_connection_id,
            "to_connection": to_connection_id,
            "mode": mode,
            "status": "success",
            "workspaces_migrated": result.get("workspaces_count", 0),
            "items_migrated": result.get("items_count", 0),
            "artifacts_migrated": result.get("artifacts_count", 0),
            "duration_seconds": result.get("duration_seconds", 0),
            "message": "Migration completed successfully"
        }
    
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

---

## 4. Integration

### `src/main.py` (Startup)

```python
from src.config import ConfigManager

# Ao iniciar MCP
def main():
    # Carrega ou cria config padrão
    config = ConfigManager.load_or_create()
    
    # Inicializa ConnectionManager com todas as conexões
    for conn in config.connections:
        if conn.enabled:
            try:
                engine = get_engine(conn.id)
                print(f"✓ Connected: {conn.name} ({conn.id})")
            except Exception as e:
                print(f"✗ Failed: {conn.name} ({conn.id}) - {e}")
    
    # Registra tools
    mcp.register_tool(connection_init_db)
    mcp.register_tool(migrate_workspaces)
    mcp.register_tool(connection_list)  # T7
    mcp.register_tool(connection_create)  # T7
    # ... resto dos tools
    
    # Roda MCP
    mcp.run()

if __name__ == "__main__":
    main()
```

---

## 5. Tests

```python
# tests/test_config.py

def test_create_default_config():
    config = ConfigManager.create_default_config()
    assert config.default == "sqlite_local"
    assert len(config.connections) == 1
    assert config.connections[0].db_type == "sqlite"

def test_load_or_create_creates_default():
    # Remove arquivo se existir
    if ConfigManager.CONNECTIONS_FILE.exists():
        ConfigManager.CONNECTIONS_FILE.unlink()
    
    config = ConfigManager.load_or_create()
    assert ConfigManager.CONNECTIONS_FILE.exists()
    assert config.default == "sqlite_local"

def test_validate_connection_sqlite():
    config = ConfigManager.create_default_config()
    conn = config.connections[0]
    result = ConfigManager.validate_connection(conn)
    assert result["status"] == "ok"

def test_connection_init_db():
    # Modo simples: já existe default
    result = connection_init_db("sqlite_local")
    assert result["status"] == "initialized"

def test_migrate_workspaces():
    # Mock: criar 2 conexões SQLite locais
    config = ConfigManager.create_default_config()
    config.connections.append(
        ConnectionConfig(
            id="sqlite_backup",
            name="Backup SQLite",
            db_type="sqlite",
            path="./backup.db",
            enabled=True
        )
    )
    ConfigManager.save(config)
    
    # Inicializar ambas
    connection_init_db("sqlite_local")
    connection_init_db("sqlite_backup")
    
    # Migrar (replace mode)
    result = migrate_workspaces("sqlite_local", "sqlite_backup", mode="replace")
    assert result["status"] == "success"
```

---

## 6. Workflow

### Simples (Plug & Play)
```bash
$ python src/main.py
✓ Loaded: .knowledge/connections.json
✓ Connected: Local SQLite (sqlite_local)
✓ Registered 44 MCP tools
Ready!
```

### Avançado (Multi-Conexões)
```bash
# Editar .knowledge/connections.json (add PostgreSQL)
$ vim .knowledge/connections.json

# Reiniciar MCP
$ python src/main.py
✓ Loaded: .knowledge/connections.json
✓ Connected: Local SQLite (sqlite_local)
✓ Connected: PostgreSQL Production (postgres_prod)
✓ Registered 44 MCP tools
Ready!

# Migrar dados
$ mcp call migrate_workspaces \
  --from-connection-id sqlite_local \
  --to-connection-id postgres_prod \
  --mode replace
✓ Migration completed: 3 workspaces, 127 items migrated (42s)
```

---

## Critério de Sucesso

✓ `pytest tests/test_config.py -v` → 8+ testes passed  
✓ Config loader carrega ou cria default  
✓ Validação Pydantic funciona (rejeita IDs inválidos, portas inválidas)  
✓ `connection_init_db(id)` cria schema  
✓ `migrate_workspaces(from, to, mode)` migra dados (replace + merge)  
✓ `.knowledge/connections.json` criado automaticamente  
✓ Modo simples: plug & play sem config  
✓ Modo avançado: multi-conexões via JSON  
✓ `ruff check src/config.py` → clean  
✓ Integração com T7 (ConnectionManager) sem breaking changes  

---

## Timeline

- Config Manager + Pydantic models: 1h
- Config Loader (create/load/save): 1h
- 2 MCP Tools (init_db + migrate): 1.5h
- Tests: 1h
- Integration + Startup: 0.5h

**Total: 5 horas**

---

## Total MCP Tools: 44

- T1-T5: 32 tools
- T7: 6 connection CRUD tools
- T9: 2 connection utility tools

**Pronto pra v0.1.0! 🚀**
