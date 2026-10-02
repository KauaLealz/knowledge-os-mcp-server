"""Artifact service: anexa arquivos a items e os lê de volta."""

import logging
import mimetypes
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import ARTIFACTS_DIR
from src.db.models import Artifact, Item
from src.exceptions import NotFoundError, ValidationError
from src.services._common import session_scope

logger = logging.getLogger(__name__)

MAX_ARTIFACT_BYTES = 100 * 1024 * 1024


def resolve_stored_path(artifacts_dir: Path, stored_name: str) -> Path:
    """Resolve o nome armazenado dentro de artifacts_dir, recusando path traversal."""
    base = artifacts_dir.resolve()
    path = (base / stored_name).resolve()
    if not path.is_relative_to(base):
        raise ValidationError(f"Caminho de artifact inválido: {stored_name}")
    return path


class ArtifactService:
    """Operações sobre artifacts (arquivos anexados a items).

    Os arquivos ficam em ARTIFACTS_DIR com um UUID como nome. Se `session` não for
    informada, cada operação abre uma sessão própria via get_session(get_engine()).
    """

    def __init__(
        self,
        session: Session | None = None,
        artifacts_dir: Path | None = None,
        connection_id: str | None = None,
    ) -> None:
        self._session = session
        self._connection_id = connection_id
        self._dir = artifacts_dir or ARTIFACTS_DIR

    def attach(self, item_id: str, file_path: str) -> Artifact:
        """Copia o arquivo para ARTIFACTS_DIR (nome UUID) e registra no banco.

        NotFoundError se o item ou o arquivo não existem; ValidationError se o caminho
        não é um arquivo regular ou excede MAX_ARTIFACT_BYTES.
        """
        source = Path(file_path)
        if not source.exists():
            raise NotFoundError(f"Arquivo não encontrado: {file_path}")
        if not source.is_file():
            raise ValidationError(f"Não é um arquivo: {file_path}")
        size = source.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            raise ValidationError(f"Arquivo maior que {MAX_ARTIFACT_BYTES} bytes: {file_path}")

        with session_scope(self._session, self._connection_id) as s:
            if s.get(Item, item_id) is None:
                raise NotFoundError(f"Item não encontrado: {item_id}")
            artifact_id = str(uuid.uuid4())
            stored = str(uuid.uuid4())
            self._dir.mkdir(parents=True, exist_ok=True)
            dest = self._dir / stored
            shutil.copyfile(source, dest)
            try:
                art = Artifact(
                    id=artifact_id,
                    item_id=item_id,
                    filename=source.name,
                    file_path=stored,
                    file_size=dest.stat().st_size,
                    mime_type=mimetypes.guess_type(source.name)[0],
                )
                s.add(art)
                s.commit()
            except Exception:
                s.rollback()
                dest.unlink(missing_ok=True)
                logger.exception("Falha ao registrar artifact de %s", file_path)
                raise
            s.refresh(art)
            logger.info("Artifact anexado: %s (item %s)", art.id, item_id)
            return art

    def list(self, item_id: str) -> list[Artifact]:
        """Lista os artifacts do item. NotFoundError se o item não existe."""
        with session_scope(self._session, self._connection_id) as s:
            if s.get(Item, item_id) is None:
                raise NotFoundError(f"Item não encontrado: {item_id}")
            rows = list(
                s.scalars(
                    select(Artifact)
                    .where(Artifact.item_id == item_id)
                    .order_by(Artifact.created_at, Artifact.id)
                )
            )
            if self._session is None:
                s.expunge_all()
            return rows

    def get(self, artifact_id: str) -> tuple[Artifact, bytes]:
        """Retorna (metadados, conteúdo). NotFoundError se o registro ou o arquivo faltam."""
        with session_scope(self._session, self._connection_id) as s:
            art = s.get(Artifact, artifact_id)
            if art is None:
                raise NotFoundError(f"Artifact não encontrado: {artifact_id}")
            path = resolve_stored_path(self._dir, art.file_path)
            if not path.is_file():
                logger.error("Arquivo do artifact %s ausente em %s", artifact_id, path)
                raise NotFoundError(f"Arquivo do artifact não encontrado: {artifact_id}")
            if self._session is None:
                s.expunge(art)
            return art, path.read_bytes()
