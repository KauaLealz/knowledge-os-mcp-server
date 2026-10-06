"""Schemas Pydantic de Artifact."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, RootModel


class ArtifactCreate(BaseModel):
    """Entrada de artifact(action="attach")."""

    item_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)


class ArtifactResponse(BaseModel):
    """Metadados de um artifact (o caminho interno no disco não é exposto)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    item_id: str
    filename: str
    file_size: int
    mime_type: str | None
    created_at: datetime | None


class ArtifactListResponse(RootModel[list[ArtifactResponse]]):
    """Lista de artifacts."""

    root: list[ArtifactResponse]
