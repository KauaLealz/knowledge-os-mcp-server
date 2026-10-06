"""Ferramentas de administração (perfil `all`): estrutura, remoção, vocabulário, backup, anexos.

Conexões, `schema_sync` e migração entre bancos ficam fora do MCP: a UI (`knowledge-mcp ui`)
faz isso melhor e o agente quase nunca precisa.
"""

import base64
from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from sqlalchemy import func, select

from knowledge_os.config import EXPORTS_DIR
from knowledge_os.db.models import Domain, Item, Workspace
from knowledge_os.db.session import connection_id_of, get_engine, get_session
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.schemas.artifact_schemas import ArtifactCreate, ArtifactResponse
from knowledge_os.schemas.domain_schemas import DomainResponse
from knowledge_os.schemas.workspace_schemas import WorkspaceResponse
from knowledge_os.services.artifact_service import ArtifactService
from knowledge_os.services.domain_service import DomainService
from knowledge_os.services.import_export_service import ImportExportService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.label_service import LabelService
from knowledge_os.services.relation_service import RelationService
from knowledge_os.services.tag_service import TagService
from knowledge_os.services.workspace_service import WorkspaceService


def structure_list(
    workspace: str | None = None, connection_id: str | None = None
) -> list[dict[str, Any]]:
    """Árvore workspaces → domains com a contagem de itens.

    **Use quando:** Ver o que existe antes de organizar, ligar um projeto ou fazer backup.
    **Retorna:** [{workspace, description, items, domains: [{name, items}]}].
    **Exemplo:** structure_list() · structure_list(workspace="agenda-api")
    **Notas:** Criar workspace/domain é implícito em item_save e repo_link.
    """
    engine = get_engine(connection_id) if connection_id else get_engine()
    cid = connection_id or connection_id_of(engine) or "default"
    session = get_session(engine)
    try:
        query = select(Workspace).where(Workspace.connection_id == cid).order_by(Workspace.name)
        if workspace:
            query = query.where((Workspace.name == workspace) | (Workspace.id == workspace))
        workspaces = list(session.scalars(query))
        counts = dict(
            session.execute(select(Item.domain_id, func.count()).group_by(Item.domain_id)).all()
        )
        out = []
        for ws in workspaces:
            domains = list(session.scalars(
                select(Domain).where(Domain.workspace_id == ws.id).order_by(Domain.name)))
            rows = [{"name": d.name, "items": counts.get(d.id, 0)} for d in domains]
            out.append({"workspace": ws.name, "description": ws.description,
                        "items": sum(r["items"] for r in rows), "domains": rows})
    finally:
        session.close()
    if workspace and not out:
        raise NotFoundError(f"Workspace não encontrado: {workspace}")
    return out


def structure_delete(
    workspace: str,
    domain: str | None = None,
    confirm: bool = False,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Remove um domain (ou o workspace inteiro) com todos os itens. Destrutivo.

    **Use quando:** O usuário pediu explicitamente para apagar.
    **Retorna:** Sem confirm: {status: preview, would_delete}. Com confirm: {status: deleted}.
    **Exemplo:** structure_delete(workspace="Teste", confirm=True)
    **Notas:** Chame primeiro sem `confirm` e mostre o preview ao usuário. Prefira backup_export
        antes, e status=deprecated (item_save) quando o histórico importar.
    """
    preview = structure_list(workspace, connection_id)[0]
    if domain:
        match = [d for d in preview["domains"] if d["name"] == domain]
        if not match:
            raise NotFoundError(f"Domain não encontrado: {domain}")
        would = {"domain": domain, "items": match[0]["items"]}
    else:
        would = {"workspace": workspace, "domains": len(preview["domains"]),
                 "items": preview["items"]}
    if not confirm:
        return {"status": "preview", "would_delete": would}
    if domain:
        ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
        DomainService(connection_id=connection_id).delete(ws_id, domain)
    else:
        WorkspaceService(connection_id=connection_id).delete(workspace)
    return {"status": "deleted", **would}


def item_delete(item_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Remove um item de vez (com tags, relações e anexos). Destrutivo.

    **Use quando:** O item está errado e não há histórico a preservar.
    **Retorna:** {status: deleted, id}.
    **Exemplo:** item_delete(item_id="...")
    **Notas:** Para aposentar mantendo o histórico, prefira item_save com status=deprecated ou
        uma relação supersedes.
    """
    ItemService(connection_id=connection_id).delete(item_id)
    return {"status": "deleted", "id": item_id}


def relation_delete(relation_id: str, connection_id: str | None = None) -> dict[str, str]:
    """Remove uma relação entre itens (o id vem em item_get → relations).

    **Use quando:** Uma relação foi criada por engano.
    **Retorna:** {status: deleted, id}.
    **Exemplo:** relation_delete(relation_id="...")
    **Notas:** Remover um supersedes não reativa o alvo: ajuste o status com item_save.
    """
    RelationService(connection_id=connection_id).delete(relation_id)
    return {"status": "deleted", "id": relation_id}


def vocabulary(
    kind: str = "tags",
    action: str = "list",
    name: str | None = None,
    id: str | None = None,
    connection_id: str | None = None,
) -> Any:
    """Vocabulário da base: tags (livres) e labels (lista controlada).

    **Use quando:** Reaproveitar tags existentes antes de criar variações, ou gerir labels.
    **Retorna:** list → [{id, name}]; create → {id, name}; delete → {status: deleted}.
    **Exemplo:** vocabulary(kind="tags") · vocabulary(kind="labels", action="create", name="lgpd")
    **Notas:** kind: tags | labels. action: list | create (name) | delete (id). Tags também são
        criadas direto no item_save.
    """
    services = {"tags": TagService, "labels": LabelService}
    if kind not in services:
        raise ValidationError("kind deve ser tags ou labels")
    svc = services[kind](connection_id=connection_id)
    if action == "list":
        return [{"id": r.id, "name": r.name} for r in svc.list()]
    if action == "create":
        if not name:
            raise ValidationError("create exige name")
        row = svc.create(name)
        return {"id": row.id, "name": row.name}
    if action == "delete":
        if not id:
            raise ValidationError("delete exige id")
        svc.delete(id)
        return {"status": "deleted", "id": id}
    raise ValidationError("action deve ser list, create ou delete")


def backup_export(
    workspace: str, domain: str | None = None, connection_id: str | None = None
) -> dict[str, Any]:
    """Exporta um workspace (ou só um domain) para um ZIP em <home>/exports.

    **Use quando:** Antes de mudanças grandes ou para levar conhecimento a outra máquina.
    **Retorna:** {status: ok, file_path, size_mb}.
    **Exemplo:** backup_export(workspace="agenda-api") · backup_export(workspace="agenda-api",
        domain="projpro")
    **Notas:** backup_import restaura (o workspace importado ganha ids novos).
    """
    ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
    svc = ImportExportService(connection_id=connection_id)
    if domain:
        dm_id = DomainService(connection_id=connection_id).get(ws_id, domain).id
        data, prefix = svc.export_domain(ws_id, dm_id), f"domain_{dm_id}"
    else:
        data, prefix = svc.export_workspace(ws_id), f"workspace_{ws_id}"
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORTS_DIR / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.zip"
    path.write_bytes(data)
    return {"status": "ok", "file_path": str(path), "size_mb": round(len(data) / 1048576, 2)}


def backup_import(
    file_path: str, workspace: str | None = None, connection_id: str | None = None
) -> dict[str, Any]:
    """Importa um ZIP de backup_export: workspace inteiro, ou um domain dentro de `workspace`.

    **Use quando:** Restaurar um backup ou trazer conhecimento de outra máquina.
    **Retorna:** {status: ok, ...workspace ou domain criado}.
    **Exemplo:** backup_import(file_path="C:/x/workspace_....zip")
    **Notas:** Use só caminhos que o usuário indicou. Nome de workspace já existente é recusado.
    """
    svc = ImportExportService(connection_id=connection_id)
    if workspace:
        ws_id = WorkspaceService(connection_id=connection_id).get(workspace).id
        dm = svc.import_domain(ws_id, file_path)
        return {"status": "ok", **DomainResponse.model_validate(dm).model_dump(mode="json")}
    ws = svc.import_workspace(file_path)
    return {"status": "ok", **WorkspaceResponse.model_validate(ws).model_dump(mode="json")}


def artifact_attach(
    item_id: str, file_path: str, connection_id: str | None = None
) -> dict[str, Any]:
    """Anexa um arquivo local a um item (copiado para <home>/artifacts, até 100 MB).

    **Use quando:** O valor do item é um arquivo (diagrama, template, script).
    **Retorna:** Metadados do anexo (id, filename, file_size, mime_type).
    **Exemplo:** artifact_attach(item_id="...", file_path="C:/docs/arquitetura.png")
    **Notas:** Use só caminhos que o usuário indicou. A lista vem em item_get → artifacts.
    """
    data = ArtifactCreate(item_id=item_id, file_path=file_path)
    art = ArtifactService(connection_id=connection_id).attach(data.item_id, data.file_path)
    return ArtifactResponse.model_validate(art).model_dump(mode="json")


def artifact_get(artifact_id: str, connection_id: str | None = None) -> dict[str, Any]:
    """Conteúdo de um anexo em base64.

    **Use quando:** Precisar do arquivo em si (confira file_size em item_get antes).
    **Retorna:** {artifact, content_base64}.
    **Exemplo:** artifact_get(artifact_id="...")
    """
    art, content = ArtifactService(connection_id=connection_id).get(artifact_id)
    return {
        "artifact": ArtifactResponse.model_validate(art).model_dump(mode="json"),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def register(mcp: FastMCP) -> None:
    """Registra as ferramentas de administração."""
    for fn in (structure_list, structure_delete, item_delete, relation_delete, vocabulary,
               backup_export, backup_import, artifact_attach, artifact_get):
        mcp.tool()(fn)
