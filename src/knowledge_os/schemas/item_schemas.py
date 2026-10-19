"""Schemas Pydantic de item (v6): entrada fina para o `ItemService` e o item completo de saída.

Entrada: `ItemCreate`/`ItemUpdate` aceitam campo extra e não validam valores — o
`ItemService.save` (via `model.validate_entry`) recusa campo desconhecido e valor fora da
taxonomia com a lista dos válidos. O local vem por id (`workspace_id`/`project_id`/`subject_id`)
e vira `workspace`/`project`/`subject` do serviço.

Saída: `ItemResponse` traz os campos v6 do item (sem scope/status/subtype/origin/ttl: a nuance
e o ciclo vivem em `tags`, o alcance vem de onde o item mora). `links` é unificado
({item, rel} | {url[, title]} | {path}).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, PlainSerializer

if TYPE_CHECKING:
    from knowledge_os.services.brain import Item

LOCATION_IDS = {"workspace_id": "workspace", "project_id": "project", "subject_id": "subject"}
# Do corpo, nunca prevalecem sobre a rota (o id vem da URL; o lugar, dos `*_id`).
BODY_IGNORED = ("id", "workspace", "project", "subject")


def _utc_z(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat() + "Z"


# Data de saída: sempre UTC com `Z` ("2026-10-08T20:31:15Z"), igual ao arquivo e ao MCP.
UtcDatetime = Annotated[datetime, PlainSerializer(_utc_z, return_type=str, when_used="json")]


class _Entry(BaseModel):
    """Corpo livre: campos conhecidos documentados; o resto vai ao serviço, que valida."""

    model_config = ConfigDict(extra="allow")

    def service_fields(self) -> dict[str, Any]:
        """Os campos enviados (só os presentes), com o local traduzido para o serviço.

        O corpo nunca vence a rota: `id` e o lugar cru (`workspace`/`project`/`subject`) do
        JSON saem — o item é o da URL e o lugar só muda pelos `*_id`, que a rota valida.
        """
        data = self.model_dump(exclude_unset=True)
        for name in BODY_IGNORED:
            data.pop(name, None)
        return {LOCATION_IDS.get(k, k): v for k, v in data.items()}

    def sent(self, name: str) -> bool:
        """O campo veio no corpo (mesmo como extra)?"""
        return name in self.model_fields_set or name in (self.model_extra or {})


class ItemCreate(_Entry):
    """Entrada de criação: `type`, `title` e `summary` obrigatórios (cobrados pelo serviço)."""

    workspace_id: str
    project_id: str | None = None
    subject_id: str | None = None
    key: str | None = None
    type: str | None = None
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    links: list[dict[str, Any]] | None = None


class ItemUpdate(_Entry):
    """Atualização parcial: só o que vier muda (tags e links substituem os atuais).

    `subject_id: null` tira o subject; `workspace_id` + `project_id` juntos movem o item.
    """

    workspace_id: str | None = None
    project_id: str | None = None
    subject_id: str | None = None
    type: str | None = None
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    links: list[dict[str, Any]] | None = None


class ItemResponse(BaseModel):
    """Item completo (com `content`); nunca o valor de um segredo (só `has_value`)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str | None = None
    workspace_id: str
    project_id: str | None = None
    subject_id: str | None = None
    workspace: str
    project: str | None = None
    subject: str | None = None
    where: str
    type: str
    title: str
    summary: str
    content: str
    tags: list[str]
    links: list[dict[str, str]]
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None
    has_value: bool | None = None  # só em `secret`: se o valor foi preenchido (nunca o valor)

    @classmethod
    def from_item(cls, item: Item) -> ItemResponse:
        """Converte um item dos services (`brain.Item`) em resposta."""
        where = item.workspace + (f"/{item.project}" if item.project else "")
        return cls(
            id=item.id, key=item.key, workspace_id=item.workspace_id,
            project_id=item.project_id, subject_id=item.subject_id, workspace=item.workspace,
            project=item.project, subject=item.subject, where=where, type=item.type,
            title=item.title, summary=item.summary, content=item.content,
            tags=sorted(item.tags), links=[dict(lk) for lk in item.links],
            created_at=item.created_at, updated_at=item.updated_at,
            has_value=bool(item.has_value) if item.type == "secret" else None,
        )


class ItemListResponse(BaseModel):
    """Página de `GET /items`: os itens da página + o total real (antes de limit/offset)."""

    items: list[ItemResponse]
    total: int
