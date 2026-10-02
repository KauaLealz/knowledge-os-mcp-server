"""Domain service: CRUD e export/import."""

from sqlalchemy.orm import Session
from src.db.models import Domain

# TODO: T2 - Implementar
# - create(workspace_id, name, description) -> Domain
# - list(workspace_id) -> [Domain]
# - get(workspace_id, name) -> Domain
# - delete(workspace_id, name) -> bool
# - export(workspace_id, name) -> bytes (ZIP)
# - import_domain(workspace_id, file_path) -> Domain
