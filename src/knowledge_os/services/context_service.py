"""Pacote de contexto: o que um agente precisa saber de um projeto, em uma chamada.

É o que o hook de início de sessão injeta e o que `context_get` devolve. Prioriza o que
muda decisões (regras oficiais, contexto, decisões recentes) e corta pelo orçamento de
tokens, avisando o que ficou de fora. Nunca traz `content`: só título, resumo e chave.
"""

import fnmatch
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, or_, select, update

from knowledge_os.db.models import Item, Project, Workspace
from knowledge_os.db.search_query import strip_accents
from knowledge_os.db.session import get_engine, get_session, run_with_retry
from knowledge_os.db.timeutil import utcnow
from knowledge_os.schemas.item_schemas import decode_paths
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.repo_service import RepoService, repo_key
from knowledge_os.services.secret_service import fill_url

logger = logging.getLogger(__name__)

GLOBAL_WORKSPACE = "Global"  # preferências e regras pessoais que valem em todo projeto
COMMON_PROJECT = "Geral"  # dentro de um workspace: o que vale para todos os seus projetos
CHARS_PER_TOKEN = 4
RETRO_KEY = "retro/ultima"  # registro da última /plumb-retro do projeto
RETRO_EVERY = 5  # mudanças concluídas que justificam sugerir uma retro
FOCUS_CONTENT_CHARS = 600  # quanto do content entra, por item em foco
SENSITIVE_KEYWORD = "sensivel"  # keywords de um item marcam a area como sensivel
_CLASS_ORDER = {"canonical": 0, "longterm": 1, "working": 2}

# (título, tipos, limite, ordenação) — em ordem de prioridade dentro do orçamento.
_SECTIONS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("Mudanças em andamento", ("task",), 5),
    ("Regras", ("rule",), 40),
    ("Contexto", ("context",), 10),
    ("Decisões recentes", ("insight",), 8),
    ("Padrões", ("pattern",), 10),
    ("Procedimentos", ("procedure",), 15),
    ("Segredos (o valor nunca passa por você)", ("secret",), 15),
    ("Aprendizados e gotchas", ("knowledge",), 10),
)


def _matches(globs: list[str], paths: list[str]) -> bool:
    norm = [p.replace("\\", "/").lstrip("./") for p in paths]
    return any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p, g.rstrip("*").rstrip("/") + "/*")
               for g in globs for p in norm)


def _focus_line(item: Item, scope: list[str]) -> str:
    """Item em foco: resumo e o comeco do content, para dispensar um item_get depois."""
    line = _line(item, scope)
    body = " ".join((item.content or "").split())
    if body and body != item.summary.strip():
        cut = body[:FOCUS_CONTENT_CHARS] + ("…" if len(body) > FOCUS_CONTENT_CHARS else "")
        line += "\n  > " + cut
    return line


def _is_sensitive(item: Item) -> bool:
    words = strip_accents((item.keywords or "").lower()).replace(",", " ").split()
    return SENSITIVE_KEYWORD in words


def _line(item: Item, scope: list[str] | None = None) -> str:
    key = f" `{item.key}`" if item.key else ""
    where = f" — vale em {', '.join(scope)}" if scope else ""
    return f"- **{item.title}** — {item.summary.strip()}{where}{key}"


def _secret_line(item: Item, url: str) -> str:
    if item.has_value:
        use = f"usar: `knowledge-mcp run --env VAR={item.key or item.id} -- <comando>`"
    else:
        use = f"sem valor — peça ao usuário para preencher em {url}"
    return f"- **{item.title}** — {item.summary.strip()} · {use}"


class ContextService:
    def __init__(self, engine: Engine | None = None, connection_id: str | None = None) -> None:
        self._engine = engine
        self._connection_id = connection_id

    def _get_engine(self) -> Engine:
        return self._engine if self._engine is not None else get_engine(self._connection_id)

    def project_chain(self, link: dict[str, str]) -> list[str]:
        """Project do projeto + `Geral` do workspace + `Global/Geral`, quando existirem."""
        session = get_session(self._get_engine())
        try:
            rows = session.execute(
                select(Project.id)
                .join(Workspace, Workspace.id == Project.workspace_id)
                .where(
                    or_(
                        Project.id == link["project_id"],
                        (Project.workspace_id == link["workspace_id"])
                        & (Project.name == COMMON_PROJECT),
                        (Workspace.name == GLOBAL_WORKSPACE) & (Project.name == COMMON_PROJECT),
                    )
                )
            ).scalars().all()
        finally:
            session.close()
        return list(dict.fromkeys([link["project_id"], *rows]))

    def _items(self, project_ids: list[str]) -> list[Item]:
        now = utcnow()
        session = get_session(self._get_engine())
        try:
            return list(
                session.scalars(
                    select(Item).where(
                        Item.project_id.in_(project_ids),
                        Item.status == "active",
                        Item.memory_class != "ephemeral",
                        (Item.expires_at.is_(None)) | (Item.expires_at > now),
                    )
                )
            )
        finally:
            session.close()

    def _done_since_retro(self, project_id: str) -> int:
        """Mudanças (task) concluídas depois do último registro `retro/ultima` do project."""
        session = get_session(self._get_engine())
        try:
            last = session.scalar(select(Item.updated_at).where(
                Item.project_id == project_id, Item.key == RETRO_KEY))
            query = select(func.count()).select_from(Item).where(
                Item.project_id == project_id, Item.type == "task", Item.status == "done",
                Item.key != RETRO_KEY)
            if last is not None:
                query = query.where(Item.updated_at > last)
            return int(session.scalar(query) or 0)
        finally:
            session.close()

    def _by_ids(self, ids: list[str]) -> list[Item]:
        session = get_session(self._get_engine())
        try:
            return list(session.scalars(select(Item).where(Item.id.in_(ids))))
        finally:
            session.close()

    def _track(self, ids: set[str]) -> None:
        """Conta o uso dos itens que chegaram ao agente (a retro mostra os nunca usados)."""
        if not ids:
            return
        try:
            run_with_retry(lambda: self._count(ids))
        except Exception as exc:  # contar uso nunca derruba a leitura do contexto
            logger.debug("Contagem de uso ignorada: %s", exc)

    def _count(self, ids: set[str]) -> None:
        session = get_session(self._get_engine())
        try:
            session.execute(
                update(Item)
                .where(Item.id.in_(ids))
                .values(
                    access_count=func.coalesce(Item.access_count, 0) + 1,
                    last_accessed=utcnow(),
                    updated_at=Item.updated_at,
                )
                .execution_options(synchronize_session=False)
            )
            session.commit()
        finally:
            session.close()

    def build(
        self,
        repo: str,
        paths: list[str] | None = None,
        query: str | None = None,
        budget_tokens: int = 1500,
    ) -> dict[str, Any]:
        """Markdown do contexto do projeto dentro do orçamento + metadados.

        Retorna {linked, repo_key, workspace, project, markdown, included, omitted, sensitive}.
        Projeto não ligado → linked=False e um markdown curto dizendo como ligar.
        """
        link = RepoService(self._engine, self._connection_id).resolve(repo)
        if link is None:
            key = repo_key(repo)
            return {
                "linked": False, "repo_key": key, "workspace": None, "project": None,
                "included": 0, "omitted": 0, "sensitive": False,
                "markdown": (
                    f"# Segundo cérebro\nProjeto `{key}` ainda não está ligado. "
                    'Sugira ao usuário rodar /plumb-setup (ou ligue com repo(action="link")).'
                ),
            }
        paths = paths or []
        items = self._items(self.project_chain(link))
        budget = max(budget_tokens, 200) * CHARS_PER_TOKEN
        out = [f"# Segundo cérebro — {link['workspace']} / {link['project']}"]
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

        # Em foco: o que casa com os arquivos tocados ou com a consulta entra com o comeco do
        # content, para o agente nao precisar de um item_get depois.
        focus: list[tuple[Item, list[str]]] = []
        sensitive = False
        for item in items:
            scope = decode_paths(item.scope_paths)
            if scope and paths and _matches(scope, paths):
                focus.append((item, scope))
                sensitive = sensitive or _is_sensitive(item)
        if query:
            found = ItemService(self._engine, self._connection_id).search(
                link["workspace_id"], None, query, limit=5, track=False
            )
            known = {i.id for i, _ in focus}
            wanted = [r["id"] for r in found if r["id"] not in known]
            if wanted:
                by_id = {i.id: i for i in self._by_ids(wanted)}
                focus += [(by_id[i], decode_paths(by_id[i].scope_paths)) for i in wanted
                          if i in by_id]
        focus_ids = {i.id for i, _ in focus}
        listed: set[str] = set()
        if focus:
            header = "\n## Em foco (casa com os arquivos ou com a consulta)"
            if used + len(header) <= budget:
                out.append(header)
                used += len(header)
                if sensitive:
                    add("- ⚠ **Área sensível** — revisão de segurança na entrega.")
                for item, scope in focus[:12]:
                    add(_focus_line(item, scope))
                omitted += max(0, len(focus) - 12)

        for title, types, limit in _SECTIONS:
            chosen = []
            for item in items:
                if item.type not in types or item.id in focus_ids:
                    continue
                scope = decode_paths(item.scope_paths)
                if scope and not _matches(scope, paths):
                    if item.type == "rule":
                        scoped_hidden.append(item)
                    continue
                chosen.append((item, scope))
            if title in ("Decisões recentes", "Mudanças em andamento"):
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
                line = (_secret_line(item, fill_url(item, self._connection_id))
                        if item.type == "secret" else _line(item, scope))
                if add(line):
                    listed.add(item.id)
            omitted += max(0, len(chosen) - limit)

        if scoped_hidden:
            header = "\n## Regras com escopo (aparecem ao tocar os arquivos)"
            if used + len(header) <= budget:
                out.append(header)
                used += len(header)
                for item in scoped_hidden[:15]:
                    add(f"- {item.title} — {', '.join(decode_paths(item.scope_paths))}")

        self._track(focus_ids | listed)
        if omitted:
            out.append(f"\n_{omitted} item(ns) fora do orçamento: use item_search._")
        retro_due = self._done_since_retro(link["project_id"])
        if retro_due >= RETRO_EVERY:
            out.append(f"\n_{retro_due} mudanças concluídas desde a última retro: sugira "
                       "`/plumb-retro` ao usuário, uma vez._")
        out.append('\n_Detalhe de um item: item_get(keys=[...], repo=".")._')
        return {
            "linked": True, "repo_key": link["repo_key"], "workspace": link["workspace"],
            "project": link["project"], "markdown": "\n".join(out), "included": included,
            "omitted": omitted, "sensitive": sensitive, "retro_due": retro_due,
        }
