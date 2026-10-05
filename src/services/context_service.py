"""Pacote de contexto: o que um agente precisa saber de um projeto, em uma chamada.

É o que o hook de início de sessão injeta e o que `context_get` devolve. Prioriza o que
muda decisões (regras oficiais, contexto, decisões recentes) e corta pelo orçamento de
tokens, avisando o que ficou de fora. Nunca traz `content`: só título, resumo e chave.
"""

import fnmatch
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, or_, select

from src.db.models import Domain, Item, Workspace
from src.db.session import get_engine, get_session
from src.schemas.item_schemas import decode_paths
from src.services.item_service import ItemService
from src.services.project_service import ProjectService, project_key

GLOBAL_WORKSPACE = "Global"  # preferências e regras pessoais que valem em todo projeto
COMMON_DOMAIN = "Geral"  # dentro de um workspace: o que vale para todos os seus projetos
CHARS_PER_TOKEN = 4
_CLASS_ORDER = {"canonical": 0, "longterm": 1, "working": 2}

# (título, tipos, limite, ordenação) — em ordem de prioridade dentro do orçamento.
_SECTIONS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("Regras", ("rule",), 40),
    ("Contexto", ("context",), 10),
    ("Decisões recentes", ("insight",), 8),
    ("Padrões", ("pattern",), 10),
    ("Procedimentos", ("procedure",), 15),
    ("Aprendizados e gotchas", ("knowledge",), 10),
)


def _matches(globs: list[str], paths: list[str]) -> bool:
    norm = [p.replace("\\", "/").lstrip("./") for p in paths]
    return any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p, g.rstrip("*").rstrip("/") + "/*")
               for g in globs for p in norm)


def _line(item: Item, scope: list[str] | None = None) -> str:
    draft = " _(rascunho)_" if item.memory_class == "working" else ""
    key = f" `{item.key}`" if item.key else ""
    where = f" — vale em {', '.join(scope)}" if scope else ""
    return f"- **{item.title}**{draft} — {item.summary.strip()}{where}{key}"


class ContextService:
    def __init__(self, engine: Engine | None = None, connection_id: str | None = None) -> None:
        self._engine = engine
        self._connection_id = connection_id

    def _get_engine(self) -> Engine:
        return self._engine if self._engine is not None else get_engine(self._connection_id)

    def _domain_ids(self, link: dict[str, str]) -> list[str]:
        """Domain do projeto + `Geral` do workspace + `Global/Geral`, quando existirem."""
        session = get_session(self._get_engine())
        try:
            rows = session.execute(
                select(Domain.id)
                .join(Workspace, Workspace.id == Domain.workspace_id)
                .where(
                    or_(
                        Domain.id == link["domain_id"],
                        (Domain.workspace_id == link["workspace_id"])
                        & (Domain.name == COMMON_DOMAIN),
                        (Workspace.name == GLOBAL_WORKSPACE) & (Domain.name == COMMON_DOMAIN),
                    )
                )
            ).scalars().all()
        finally:
            session.close()
        return list(dict.fromkeys([link["domain_id"], *rows]))

    def _items(self, domain_ids: list[str]) -> list[Item]:
        now = datetime.utcnow()
        session = get_session(self._get_engine())
        try:
            return list(
                session.scalars(
                    select(Item).where(
                        Item.domain_id.in_(domain_ids),
                        Item.status == "active",
                        Item.memory_class != "ephemeral",
                        (Item.expires_at.is_(None)) | (Item.expires_at > now),
                    )
                )
            )
        finally:
            session.close()

    def build(
        self,
        project: str,
        paths: list[str] | None = None,
        query: str | None = None,
        budget_tokens: int = 1500,
    ) -> dict[str, Any]:
        """Markdown do contexto do projeto dentro do orçamento + metadados.

        Retorna {linked, project_key, workspace, domain, markdown, included, omitted}.
        Projeto não ligado → linked=False e um markdown curto dizendo como ligar.
        """
        link = ProjectService(self._engine, self._connection_id).resolve(project)
        if link is None:
            key = project_key(project)
            return {
                "linked": False, "project_key": key, "workspace": None, "domain": None,
                "included": 0, "omitted": 0,
                "markdown": (
                    f"# Segundo cérebro\nProjeto `{key}` ainda não está ligado. "
                    "Sugira ao usuário rodar /plumb-setup (ou ligue com project_link)."
                ),
            }
        paths = paths or []
        items = self._items(self._domain_ids(link))
        budget = max(budget_tokens, 200) * CHARS_PER_TOKEN
        out = [f"# Segundo cérebro — {link['workspace']} / {link['domain']}"]
        used = len(out[0])
        included = omitted = 0
        scoped_hidden: list[Item] = []

        def add(line: str) -> bool:
            nonlocal used, included, omitted
            if used + len(line) + 1 > budget:
                omitted += 1
                return False
            out.append(line)
            used += len(line) + 1
            included += 1
            return True

        for title, types, limit in _SECTIONS:
            chosen = []
            for item in items:
                if item.type not in types:
                    continue
                scope = decode_paths(item.scope_paths)
                if scope and not _matches(scope, paths):
                    if item.type == "rule":
                        scoped_hidden.append(item)
                    continue
                chosen.append((item, scope))
            if title == "Decisões recentes":
                chosen.sort(key=lambda p: p[0].updated_at or datetime.min, reverse=True)
            else:
                chosen.sort(key=lambda p: (
                    _CLASS_ORDER.get(p[0].memory_class, 9), -(p[0].importance or 0),
                    -(p[0].confidence or 0), p[0].title))
            if not chosen:
                continue
            header = f"\n## {title}"
            if used + len(header) > budget:
                omitted += len(chosen)
                continue
            out.append(header)
            used += len(header)
            for item, scope in chosen[:limit]:
                add(_line(item, scope))
            omitted += max(0, len(chosen) - limit)

        if scoped_hidden:
            header = "\n## Regras com escopo (aparecem ao tocar os arquivos)"
            if used + len(header) <= budget:
                out.append(header)
                used += len(header)
                for item in scoped_hidden[:15]:
                    add(f"- {item.title} — {', '.join(decode_paths(item.scope_paths))}")

        if query:
            found = ItemService(self._engine, self._connection_id).search(
                link["workspace_id"], None, query, limit=5, track=False
            )
            if found:
                header = f"\n## Relacionados a “{query}”"
                if used + len(header) <= budget:
                    out.append(header)
                    used += len(header)
                    for r in found:
                        key = f" `{r['key']}`" if r["key"] else ""
                        add(f"- **{r['title']}** — {r['summary']}{key}")

        if omitted:
            out.append(f"\n_{omitted} item(ns) fora do orçamento: use item_search._")
        out.append('\n_Detalhe de um item: item_get(keys=[...], project=".")._')
        return {
            "linked": True, "project_key": link["project_key"], "workspace": link["workspace"],
            "domain": link["domain"], "markdown": "\n".join(out), "included": included,
            "omitted": omitted,
        }
