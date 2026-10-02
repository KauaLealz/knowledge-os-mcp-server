"""Import/Export service: ZIP handling."""

from sqlalchemy.orm import Session

# TODO: T5 - Implementar
# - export_workspace(workspace_id) -> bytes (ZIP)
#   - manifest.json: metadados
#   - workspace.json: definição
#   - domains/: estrutura
#   - items/: JSON dos items
#   - artifacts/: binários
#   - relations/: relações
# - import_workspace(file_path) -> Workspace
#   - Restaura estrutura completa
#   - Cria IDs novos (preserva semântica, não PKs)
