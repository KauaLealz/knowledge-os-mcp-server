"""Configuração do MCP Knowledge OS."""

import os
from pathlib import Path

# Diretórios
PROJECT_ROOT = Path(__file__).parent.parent
DATABASE_DIR = PROJECT_ROOT / "database"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
EXPORTS_DIR = PROJECT_ROOT / "exports"
BACKUPS_DIR = PROJECT_ROOT / "backups"

# Criar diretórios se não existirem
for d in [DATABASE_DIR, ARTIFACTS_DIR, EXPORTS_DIR, BACKUPS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Database
DB_PATH = os.getenv("MCP_DB_PATH", str(DATABASE_DIR / "knowledge.db"))
DB_KEY = os.getenv("MCP_DB_KEY", None)

# SQLAlchemy URL
if DB_KEY:
    # SQLCipher com criptografia AES-256
    DB_URL = f"sqlite+pysqlcipher:///:memory:?uri={DB_PATH}&key={DB_KEY}"
else:
    # SQLite simples
    DB_URL = f"sqlite:///{DB_PATH}"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Validação
def validate_config():
    """Valida configuração na inicialização."""
    if DB_KEY and len(DB_KEY) < 16:
        raise ValueError("MCP_DB_KEY deve ter no mínimo 16 caracteres")

    if not DATABASE_DIR.exists():
        raise FileNotFoundError(f"DATABASE_DIR não existe: {DATABASE_DIR}")
