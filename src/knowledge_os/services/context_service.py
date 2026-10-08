"""Pacote de contexto: o que um agente precisa saber de um projeto, em uma chamada.

É o que o hook de início de sessão injeta e o que `context_get` devolve. Prioriza o que
muda decisões (regras oficiais, contexto, decisões recentes) e corta pelo orçamento de
tokens, avisando o que ficou de fora. Nunca traz `content`: só título, resumo e chave.
"""

import fnmatch
import logging
from datetime import datetime
from typing import Any

from knowledge_os.services.brain import Brain, Item, is_expired, utcnow
from knowledge_os.services.item_file import slugify
from knowledge_os.services.item_service import run_search
from knowledge_os.services.repo_service import RepoService, repo_key
from knowledge_os.services.secret_service import fill_url
from knowledge_os.storage.search import strip_accents

logger = logging.getLogger(__name__)

GLOBAL_WORKSPACE = "Global"  # preferências e regras pessoais que valem em todo projeto
COMMON_PROJECT = "Geral"  # dentro de um workspace: o que vale para todos os seus projetos
CHARS_PER_TOKEN = 4
FOCUS_CONTENT_CHARS = 600  # quanto do content entra, por item em foco
SENSITIVE_KEYWORD = "sensivel"  # keywords de um item marcam a area como sensivel
_CLASS_ORDER = {"canonical": 0, "longterm": 1, "working": 2}

# (título, tipos, limite, ordenação) — em ordem de prioridade dentro do orçamento.
_SECTIONS: tuple[tuple[str, tuple[str, ...], int], ...] = (
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
    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    @staticmethod
    def project_chain(link: dict[str, str]) -> list[tuple[str, str]]:
        """(workspace, project) do projeto + `Geral` do workspace + `Global/Geral`."""
        chain = [
            (link["workspace_id"], link["project_id"]),
            (link["workspace_id"], slugify(COMMON_PROJECT)),
            (slugify(GLOBAL_WORKSPACE), slugify(COMMON_PROJECT)),
        ]
        return list(dict.fromkeys(chain))

    @staticmethod
    def _items(brain: Brain, chain: list[tuple[str, str]]) -> list[Item]:
        wanted = set(chain)
        now = utcnow()
        records = [
            r for r in brain.snapshot.records.values()
            if (slugify(r.workspace or ""), slugify(r.project or "")) in wanted
            and r.status == "active" and r.memory_class != "ephemeral"
            and not is_expired(r, now)
        ]
        records.sort(key=lambda r: (r.created_at, r.path))
        return brain.views(records)

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
        brain = Brain(self._connection_id)
        link = RepoService(brain.cid).resolve(repo)
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
        items = self._items(brain, self.project_chain(link))
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
            scope = item.scope_paths
            if scope and paths and _matches(scope, paths):
                focus.append((item, scope))
                sensitive = sensitive or _is_sensitive(item)
        if query:
            found = run_search(brain, link["workspace_id"], None, query, limit=5)
            known = {i.id for i, _ in focus}
            for record, _score in found:
                if record.id not in known:
                    item = brain.view(record)
                    focus.append((item, item.scope_paths))
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
                scope = item.scope_paths
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
                line = (_secret_line(item, fill_url(item, brain.cid))
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
                    add(f"- {item.title} — {', '.join(item.scope_paths)}")

        if focus_ids | listed:
            brain.track(focus_ids | listed)
        if omitted:
            out.append(f"\n_{omitted} item(ns) fora do orçamento: use item_search._")
        out.append('\n_Detalhe de um item: item_get(keys=[...], repo=".")._')
        return {
            "linked": True, "repo_key": link["repo_key"], "workspace": link["workspace"],
            "project": link["project"], "markdown": "\n".join(out), "included": included,
            "omitted": omitted, "sensitive": sensitive,
        }
