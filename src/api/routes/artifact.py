"""Rotas de artifacts (upload multipart, download binário, remoção)."""

import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.auth import verify_token
from src.api.deps import get_artifacts_dir, get_session_dep
from src.api.routes._helpers import get_or_404
from src.api.schemas.responses import ArtifactResponse
from src.db.models import Artifact
from src.exceptions import ValidationError
from src.services.artifact_service import ArtifactService, resolve_stored_path

router = APIRouter(dependencies=[Depends(verify_token)])


def _safe_filename(raw: str | None) -> str:
    """Só o nome-base: descarta diretórios (inclusive `..`) vindos do cliente."""
    name = PureWindowsPath(PurePosixPath(raw or "").name).name
    if name in ("", ".", ".."):
        raise ValidationError("Nome de arquivo inválido")
    return name


@router.get("/artifacts", response_model=list[ArtifactResponse])
def list_artifacts(
    item_id: str | None = None,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
):
    if item_id:
        return ArtifactService(session, artifacts_dir).list(item_id)
    return list(session.scalars(select(Artifact).order_by(Artifact.created_at, Artifact.id)))


@router.post("/artifacts", status_code=status.HTTP_201_CREATED, response_model=ArtifactResponse)
def upload_artifact(
    item_id: str,
    file: UploadFile,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
):
    filename = _safe_filename(file.filename)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / filename
        with src.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return ArtifactService(session, artifacts_dir).attach(item_id, str(src))


@router.get("/artifacts/{id}")
def download_artifact(
    id: str,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
) -> Response:
    art, content = ArtifactService(session, artifacts_dir).get(id)
    return Response(
        content=content,
        media_type=art.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{art.filename}"'},
    )


@router.delete("/artifacts/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artifact(
    id: str,
    session: Session = Depends(get_session_dep),
    artifacts_dir: Path = Depends(get_artifacts_dir),
) -> Response:
    art = get_or_404(session, Artifact, id, "Artifact")
    path = resolve_stored_path(artifacts_dir, art.file_path)
    session.delete(art)
    session.commit()
    path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
