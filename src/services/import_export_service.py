"""Import/Export service: pacotes ZIP de workspace e domain.

Layout do ZIP de workspace: manifest.json, workspace.json, relations.json e
artifacts/<id-original>. O de domain troca workspace.json por domain.json. Na importação
todos os ids são regenerados; o vínculo entre registros é preservado por um mapa
id-antigo -> id-novo.
"""

import io
import json
import logging
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config import ARTIFACTS_DIR
from src.db.models import (
    DEFAULT_CONNECTION_ID,
    Artifact,
    Domain,
    Item,
    Label,
    Relation,
    Tag,
    Workspace,
)
from src.exceptions import NotFoundError, ValidationError
from src.schemas.item_schemas import ItemCreate
from src.services._common import (
    EXPORT_VERSION,
    domain_to_dict,
    item_to_dict,
    session_scope,
    utc_now_iso,
    workspace_to_dict,
)
from src.services.artifact_service import resolve_stored_path

logger = logging.getLogger(__name__)

MAX_ZIP_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
_MALFORMED = (KeyError, TypeError, ValueError, AttributeError)


def _parse_dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ImportExportService:
    """Exporta/importa workspaces e domains como arquivos ZIP.

    Se `session` não for informada, cada operação abre uma sessão própria via
    get_session(get_engine()). As importações são atômicas: em caso de erro nada é
    gravado no banco e os arquivos de artifact já copiados são removidos.
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

    # ------------------------------------------------------------------ export

    def export_workspace(self, workspace_id: str) -> bytes:
        """Gera o ZIP (bytes) do workspace. NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            ws = s.get(Workspace, workspace_id)
            if ws is None:
                logger.error("Export de workspace inexistente: %s", workspace_id)
                raise NotFoundError(f"Workspace não encontrado: {workspace_id}")
            domains = sorted(ws.domains, key=lambda d: d.name)
            items = sorted(ws.items, key=lambda i: (i.created_at or datetime.min, i.id))
            relations, artifacts, files = self._collect(s, items)
            counts = {
                "domains": len(domains),
                "items": len(items),
                "relations": len(relations),
                "artifacts": len(artifacts),
            }
            payload = {
                "workspace": workspace_to_dict(ws),
                "domains": [domain_to_dict(d) for d in domains],
                "items": [item_to_dict(i) for i in items],
                "relations": relations,
                "artifacts": artifacts,
            }
            logger.info("Workspace exportado: %s", ws.name)
            return self._pack("workspace", ws.name, "workspace.json", payload, files, counts)

    def export_domain(self, workspace_id: str, domain_id: str) -> bytes:
        """Gera o ZIP (bytes) de um domain e seus items. NotFoundError se não existe."""
        with session_scope(self._session, self._connection_id) as s:
            dm = s.get(Domain, domain_id)
            if dm is None or dm.workspace_id != workspace_id:
                logger.error("Export de domain inexistente: %s", domain_id)
                raise NotFoundError(f"Domain não encontrado: {domain_id}")
            items = sorted(dm.items, key=lambda i: (i.created_at or datetime.min, i.id))
            relations, artifacts, files = self._collect(s, items)
            counts = {
                "items": len(items),
                "relations": len(relations),
                "artifacts": len(artifacts),
            }
            payload = {
                "domain": domain_to_dict(dm),
                "items": [item_to_dict(i) for i in items],
                "relations": relations,
                "artifacts": artifacts,
            }
            logger.info("Domain exportado: %s", dm.name)
            return self._pack("domain", dm.name, "domain.json", payload, files, counts)

    def _collect(
        self, s: Session, items: list[Item]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bytes]]:
        """Relações internas ao conjunto de items, metadados de artifacts e seus binários."""
        ids = {i.id for i in items}
        rels = [
            {
                "id": r.id,
                "source_item_id": r.source_item_id,
                "target_item_id": r.target_item_id,
                "relation_type": r.relation_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in s.scalars(select(Relation).order_by(Relation.created_at, Relation.id))
            if r.source_item_id in ids and r.target_item_id in ids
        ]
        artifacts: list[dict[str, Any]] = []
        files: dict[str, bytes] = {}
        rows = s.scalars(
            select(Artifact).where(Artifact.item_id.in_(ids)).order_by(Artifact.id)
        ) if ids else []
        for a in rows:
            try:
                path = resolve_stored_path(self._dir, a.file_path)
                files[a.id] = path.read_bytes()
            except (OSError, ValidationError):
                logger.warning("Arquivo do artifact %s indisponível; omitido do export", a.id)
                continue
            artifacts.append(
                {
                    "id": a.id,
                    "item_id": a.item_id,
                    "filename": a.filename,
                    "file_size": a.file_size,
                    "mime_type": a.mime_type,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
            )
        return rels, artifacts, files

    @staticmethod
    def _pack(
        kind: str,
        name: str,
        payload_name: str,
        payload: dict[str, Any],
        files: dict[str, bytes],
        counts: dict[str, int],
    ) -> bytes:
        manifest = {
            "version": EXPORT_VERSION,
            "type": kind,
            "name": name,
            "exported_at": utc_now_iso(),
            "counts": counts,
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr(payload_name, json.dumps(payload, ensure_ascii=False, indent=2))
            z.writestr("relations.json", json.dumps(payload["relations"], ensure_ascii=False))
            for artifact_id, data in files.items():
                z.writestr(f"artifacts/{artifact_id}", data)
        return buf.getvalue()

    # ------------------------------------------------------------------ import

    def import_workspace(self, zip_path: str) -> Workspace:
        """Cria um workspace novo (ids novos) a partir do ZIP.

        ValidationError se o ZIP é inválido/malformado ou o nome do workspace já existe;
        NotFoundError se o arquivo não existe.
        """
        with self._open(zip_path, "workspace") as z:
            payload = self._read_json(z, "workspace.json")
            written: list[Path] = []
            with session_scope(self._session, self._connection_id) as s:
                try:
                    wd = payload["workspace"]
                    name = wd["name"]
                    cid = self._connection_id or DEFAULT_CONNECTION_ID
                    if s.scalar(
                        select(Workspace.id).where(
                            Workspace.name == name, Workspace.connection_id == cid
                        )
                    ):
                        raise ValidationError(f"Workspace já existe: {name}")
                    ws = Workspace(
                        id=str(uuid.uuid4()),
                        connection_id=cid,
                        name=name,
                        description=wd.get("description"),
                        created_at=_parse_dt(wd.get("created_at")),
                        updated_at=_parse_dt(wd.get("updated_at")),
                    )
                    s.add(ws)
                    s.flush()
                    domain_ids: dict[str, str] = {}
                    for d in payload["domains"]:
                        domain_ids[d["id"]] = self._add_domain(s, ws.id, d)
                    s.flush()
                    self._restore_items(s, z, ws.id, domain_ids, payload, written, None)
                    s.commit()
                except Exception as exc:
                    self._abort(s, written, exc)
                s.refresh(ws)
                logger.info("Workspace importado: %s (%s)", ws.name, ws.id)
                return ws

    def import_domain(self, workspace_id: str, zip_path: str) -> Domain:
        """Cria um domain novo (ids novos) no workspace a partir do ZIP.

        NotFoundError se workspace ou arquivo não existem; ValidationError se o ZIP é
        inválido/malformado ou o domain já existe no workspace.
        """
        with self._open(zip_path, "domain") as z:
            payload = self._read_json(z, "domain.json")
            written: list[Path] = []
            with session_scope(self._session, self._connection_id) as s:
                try:
                    if s.get(Workspace, workspace_id) is None:
                        raise NotFoundError(f"Workspace não encontrado: {workspace_id}")
                    dd = payload["domain"]
                    exists = s.scalar(
                        select(Domain.id).where(
                            Domain.workspace_id == workspace_id, Domain.name == dd["name"]
                        )
                    )
                    if exists:
                        raise ValidationError(f"Domain já existe: {dd['name']}")
                    new_id = self._add_domain(s, workspace_id, dd)
                    s.flush()
                    self._restore_items(
                        s, z, workspace_id, {dd["id"]: new_id}, payload, written, new_id
                    )
                    s.commit()
                except Exception as exc:
                    self._abort(s, written, exc)
                dm = s.get(Domain, new_id)
                assert dm is not None
                s.refresh(dm)
                logger.info("Domain importado: %s (%s)", dm.name, dm.id)
                return dm

    @staticmethod
    def _abort(s: Session, written: list[Path], exc: Exception) -> None:
        """Desfaz a importação (banco e arquivos) e relança o erro como exceção de domínio."""
        s.rollback()
        for p in written:
            p.unlink(missing_ok=True)
        logger.error("Importação abortada: %s", exc)
        if isinstance(exc, (_MALFORMED)):
            raise ValidationError(f"Arquivo de importação malformado: {exc!r}") from exc
        if isinstance(exc, IntegrityError):
            raise ValidationError(f"Dados de importação conflitantes: {exc.orig}") from exc
        raise exc

    @staticmethod
    def _add_domain(s: Session, workspace_id: str, d: dict[str, Any]) -> str:
        new_id = str(uuid.uuid4())
        s.add(
            Domain(
                id=new_id,
                workspace_id=workspace_id,
                name=d["name"],
                description=d.get("description"),
                created_at=_parse_dt(d.get("created_at")),
                updated_at=_parse_dt(d.get("updated_at")),
            )
        )
        return new_id

    def _restore_items(
        self,
        s: Session,
        z: zipfile.ZipFile,
        workspace_id: str,
        domain_ids: dict[str, str],
        payload: dict[str, Any],
        written: list[Path],
        default_domain: str | None,
    ) -> None:
        """Recria items (com tags/labels), relações e artifacts com ids novos."""
        item_ids: dict[str, str] = {}
        cache: dict[tuple[type, str], Tag | Label] = {}

        def named(model: type[Tag] | type[Label], name: str) -> Tag | Label:
            key = (model, name)
            if key not in cache:
                row = s.scalar(select(model).where(model.name == name))
                if row is None:
                    row = model(id=str(uuid.uuid4()), name=name)
                    s.add(row)
                    s.flush()
                cache[key] = row
            return cache[key]

        for it in payload["items"]:
            domain_id = domain_ids.get(it.get("domain_id"), default_domain)
            if domain_id is None:
                raise ValidationError(f"Item referencia domain desconhecido: {it.get('domain_id')}")
            try:
                ItemCreate(
                    workspace_id=workspace_id, domain_id=domain_id,
                    **{
                        k: it[k]
                        for k in ("type", "memory_class", "title", "summary", "content")
                    },
                    confidence=it.get("confidence"), importance=it.get("importance"),
                    ttl_days=it.get("ttl_days"),
                )
            except PydanticValidationError as exc:
                raise ValidationError(f"Item inválido no pacote: {exc.errors()[0]['msg']}") from exc
            new_id = str(uuid.uuid4())
            item_ids[it["id"]] = new_id
            item = Item(
                id=new_id,
                workspace_id=workspace_id,
                domain_id=domain_id,
                type=it["type"],
                memory_class=it["memory_class"],
                title=it["title"],
                summary=it["summary"],
                content=it["content"],
                confidence=it.get("confidence"),
                importance=it.get("importance"),
                ttl_days=it.get("ttl_days"),
                created_at=_parse_dt(it.get("created_at")),
                updated_at=_parse_dt(it.get("updated_at")),
            )
            item.tags = [named(Tag, n) for n in dict.fromkeys(it.get("tags", []))]  # type: ignore[misc]
            item.labels = [named(Label, n) for n in dict.fromkeys(it.get("labels", []))]  # type: ignore[misc]
            s.add(item)
            s.flush()

        for r in payload["relations"]:
            if r["source_item_id"] not in item_ids or r["target_item_id"] not in item_ids:
                logger.warning("Relação %s ignorada: item fora do pacote", r.get("id"))
                continue
            s.add(
                Relation(
                    id=str(uuid.uuid4()),
                    source_item_id=item_ids[r["source_item_id"]],
                    target_item_id=item_ids[r["target_item_id"]],
                    relation_type=r["relation_type"],
                    created_at=_parse_dt(r.get("created_at")),
                )
            )
        s.flush()

        members = set(z.namelist())
        self._dir.mkdir(parents=True, exist_ok=True)
        for a in payload.get("artifacts", []):
            member = f"artifacts/{a['id']}"
            if member not in members or a["item_id"] not in item_ids:
                raise ValidationError(f"Artifact inconsistente no pacote: {a['id']}")
            stored = str(uuid.uuid4())
            dest = self._dir / stored
            data = z.read(member)
            dest.write_bytes(data)
            written.append(dest)
            s.add(
                Artifact(
                    id=str(uuid.uuid4()),
                    item_id=item_ids[a["item_id"]],
                    filename=a["filename"],
                    file_path=stored,
                    file_size=len(data),
                    mime_type=a.get("mime_type"),
                    created_at=_parse_dt(a.get("created_at")),
                )
            )
        s.flush()

    # ------------------------------------------------------------------ zip I/O

    @staticmethod
    def _open(zip_path: str, expected_type: str) -> zipfile.ZipFile:
        """Abre o ZIP e valida o manifest (tipo e versão)."""
        path = Path(zip_path)
        if not path.is_file():
            raise NotFoundError(f"Arquivo ZIP não encontrado: {zip_path}")
        try:
            z = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise ValidationError(f"Arquivo não é um ZIP válido: {zip_path}") from exc
        try:
            if sum(i.file_size for i in z.infolist()) > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValidationError("ZIP excede o tamanho máximo descompactado")
            manifest = ImportExportService._read_json(z, "manifest.json")
            if not isinstance(manifest, dict):
                raise ValidationError("manifest.json inválido no pacote")
            if manifest.get("type") != expected_type:
                raise ValidationError(
                    f"Tipo de pacote inválido: esperado '{expected_type}', "
                    f"recebido '{manifest.get('type')}'"
                )
            if manifest.get("version") != EXPORT_VERSION:
                raise ValidationError(f"Versão de pacote não suportada: {manifest.get('version')}")
        except Exception:
            z.close()
            raise
        return z

    @staticmethod
    def _read_json(z: zipfile.ZipFile, name: str) -> Any:
        try:
            return json.loads(z.read(name))
        except KeyError as exc:
            raise ValidationError(f"Pacote sem {name}") from exc
        except (ValueError, zipfile.BadZipFile) as exc:
            raise ValidationError(f"{name} inválido no pacote") from exc
