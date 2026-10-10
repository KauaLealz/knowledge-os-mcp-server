"""Pacote de contexto: o que um agente precisa saber de um repositório, em uma chamada.

É o que o hook de início de sessão injeta (`knowledge-mcp context`). Usa a mesma cadeia de
alcance da busca (`services.scope.reach`, a partir do project ligado ao repositório) e monta
seções nesta ordem:

1. **Em foco** — itens que casam `paths` (pelos `scope_paths`) ou a `query` (pela busca do
   `ItemService`), com o começo do `content` (~600 caracteres), para dispensar um `item_get`;
2. **⚠ Em revisão** — status `review` (pode estar errado: confira antes de seguir);
3. **Segurança** — `rule/security`;
4. **Regras** — as demais regras, cada linha com `[subtipo]`;
5. **Contexto**; 6. **Como fazer** (só títulos); 7. **Specs ativas** (`active`/`draft`, com o
   `summary`, que diz o andamento); 8. **Segredos** (estado e como usar, nunca o valor);
9. **Regras com escopo** — regras com `scope_paths`: com `paths`, as que casam; sem `paths`,
   todas, como lembrete (título e globs). Itens com `scope_paths` que não casam ficam de fora
   das outras seções (valem para outra área do código).

Linha de item de fora do project do repositório leva a origem: `[global]` (scope efetivo
global) ou `[<workspace>]`. Sensível = algum `rule/security` casou `paths` (a palavra
`sensivel` em `keywords` não tem mais efeito). O texto respeita o orçamento em tokens
(~4 caracteres por token) e lista o que ficou de fora. Cada item que entra soma `shown`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from knowledge_os.config import NO_CONNECTION_MESSAGE
from knowledge_os.exceptions import NoConnectionError
from knowledge_os.services import scope as scope_mod
from knowledge_os.services.brain import Brain, is_expired, utcnow
from knowledge_os.services.item_file import slugify
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.repo_service import RepoService, repo_key
from knowledge_os.services.secret_service import fill_url
from knowledge_os.storage.files import ItemRecord
from knowledge_os.storage.search import paths_match

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4
MIN_BUDGET = 200
FOCUS_CONTENT_CHARS = 600  # quanto do content entra, por item em foco
FOCUS_LIMIT = 12
QUERY_LIMIT = 5
OMITTED_LISTED = 10  # keys omitidas citadas no rodapé

LINK_HINT = (
    "Ligue com `repo(action=\"link\", repo=\".\", workspace=\"<workspace>\", "
    "project=\"<project>\")` ou sugira ao usuário rodar /plumb-setup."
)

# (título, filtro, limite, só título?) — em ordem; "Em foco" e "Regras com escopo" à parte.
Section = tuple[str, Callable[[ItemRecord], bool], int, bool]
_SECTIONS: tuple[Section, ...] = (
    ("⚠ Em revisão", lambda r: r.status == "review", 10, False),
    ("Segurança", lambda r: r.type == "rule" and r.subtype == "security", 20, False),
    ("Regras", lambda r: r.type == "rule" and r.subtype != "security", 40, False),
    ("Contexto", lambda r: r.type == "context", 10, False),
    ("Como fazer", lambda r: r.type == "howto", 20, True),
    ("Specs ativas", lambda r: r.type == "spec", 10, False),
    ("Segredos (o valor nunca passa por você)", lambda r: r.type == "secret", 15, False),
)


def _empty(key: str | None, markdown: str) -> dict[str, Any]:
    return {"linked": False, "repo_key": key, "workspace": None, "project": None,
            "markdown": markdown, "included": 0, "omitted": 0, "omitted_keys": [],
            "sensitive": False}


def _visible(record: ItemRecord, now: Any) -> bool:
    """Vigente no pacote: sem arquivados, vencidos nem specs fechadas."""
    if record.status == "archived" or is_expired(record, now):
        return False
    return not (record.type == "spec" and record.status not in ("active", "draft", "review"))


class _Pack:
    """Acumula as linhas dentro do orçamento e conta o que entrou e o que ficou de fora."""

    def __init__(self, title: str, budget_chars: int) -> None:
        self.lines = [title]
        self.used = len(title)
        self.budget = budget_chars
        self.ids: list[str] = []
        self.omitted: list[ItemRecord] = []

    def fits(self, text: str) -> bool:
        return self.used + len(text) + 1 <= self.budget

    def header(self, text: str, pending: list[ItemRecord]) -> bool:
        if not self.fits(text):
            self.omitted.extend(pending)
            return False
        self.lines.append(text)
        self.used += len(text) + 1
        return True

    def item(self, record: ItemRecord, text: str) -> bool:
        if not self.fits(text):
            self.omitted.append(record)
            return False
        self.lines.append(text)
        self.used += len(text) + 1
        self.ids.append(record.id)
        return True


class ContextService:
    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    def build(
        self,
        repo: str,
        paths: list[str] | None = None,
        query: str | None = None,
        budget_tokens: int = 1500,
    ) -> dict[str, Any]:
        """Markdown do contexto do repositório dentro do orçamento + metadados.

        Retorna `{linked, repo_key, workspace, project, markdown, included, omitted,
        omitted_keys, sensitive}`. Repositório não ligado → `linked=False` e um texto curto com
        a chamada que liga; sem conexão → `linked=False` e `NO_CONNECTION_MESSAGE`.
        """
        try:
            brain = Brain(self._connection_id)
        except NoConnectionError:
            return _empty(None, f"# Segundo cérebro\n{NO_CONNECTION_MESSAGE}")
        link = RepoService(brain.cid).resolve(repo)
        if link is None:
            key = repo_key(repo)
            return _empty(key, f"# Segundo cérebro\nRepositório `{key}` ainda não está ligado "
                               f"a um project. {LINK_HINT}")
        paths = [p for p in paths or [] if p and p.strip()]
        viewpoint = (link["workspace_id"], link["project_id"])
        snap = brain.snapshot
        now = utcnow()
        pool = [r for r, _dist in scope_mod.reach(snap, viewpoint) if _visible(r, now)]
        usage = brain.usage()

        def order(records: list[ItemRecord]) -> list[ItemRecord]:
            # `reach` já vem do mais perto ao mais longe; dentro da mesma distância, o mais
            # usado e o mais recente primeiro.
            near = {r.id: scope_mod.distance(snap, r, viewpoint) or 0.0 for r in records}

            def used(r: ItemRecord) -> int:
                use = usage.get(r.id) or {}
                return int(use.get("helped") or 0) + int(use.get("opened") or 0)

            return sorted(records, key=lambda r: (-near[r.id], -used(r),
                                                  -r.updated_at.timestamp(), r.path))

        def mark(record: ItemRecord) -> str:
            if (slugify(record.workspace or ""), slugify(record.project or "")) == viewpoint:
                return ""
            if snap.effective_scope(record) == "global":
                return "[global] "
            return f"[{record.workspace}] "

        def line(record: ItemRecord, title_only: bool = False) -> str:
            tag = f"[{record.subtype}] " if record.type == "rule" and record.subtype else ""
            key = f" `{record.key}`" if record.key else ""
            if title_only:
                return f"- {tag}{mark(record)}**{record.title}**{key}"
            return f"- {tag}{mark(record)}**{record.title}** — {record.summary.strip()}{key}"

        # ---- em foco: paths (scope_paths) e query (busca do ItemService)
        focus: list[ItemRecord] = []
        if paths:
            focus = order([r for r in pool if r.scope_paths and paths_match(r, paths)])
        if query and query.strip():
            found = ItemService(brain.cid).search(query.strip(), viewpoint=viewpoint,
                                                  limit=QUERY_LIMIT)
            known = {r.id for r in focus}
            for row in found.get("results", []):
                record = snap.get(row["id"])
                if record is not None and record.id not in known and _visible(record, now):
                    focus.append(record)
                    known.add(record.id)
        focus_ids = {r.id for r in focus}
        sensitive = bool(paths) and any(r.type == "rule" and r.subtype == "security"
                                        and paths_match(r, paths) for r in pool)

        budget = max(budget_tokens, MIN_BUDGET) * CHARS_PER_TOKEN
        pack = _Pack(f"# Segundo cérebro — {link['workspace']} / {link['project']}", budget)

        if focus:
            shown = focus[:FOCUS_LIMIT]
            pack.omitted.extend(focus[FOCUS_LIMIT:])
            if pack.header("\n## Em foco (casa com os arquivos ou com a consulta)", shown):
                if sensitive:
                    pack.header("- ⚠ **Área sensível** (rule/security): revisão de segurança "
                                "na entrega.", [])
                for record in shown:
                    pack.item(record, self._focus_line(line(record), record))

        # ---- seções gerais: sem o que está em foco e sem itens de outra área do código
        rest = [r for r in pool if r.id not in focus_ids and not r.scope_paths]
        taken: set[str] = set()
        for title, pick, limit, title_only in _SECTIONS:
            chosen = order([r for r in rest if r.id not in taken and pick(r)])
            taken.update(r.id for r in chosen)
            if not chosen:
                continue
            pack.omitted.extend(chosen[limit:])
            chosen = chosen[:limit]
            if not pack.header(f"\n## {title}", chosen):
                continue
            for record in chosen:
                text = (self._secret_line(brain, record, mark(record))
                        if record.type == "secret" else line(record, title_only))
                pack.item(record, text)

        # ---- regras com escopo: as que casam `paths` ou, sem paths, todas (lembrete)
        scoped = order([r for r in pool if r.type == "rule" and r.scope_paths
                        and (not paths or paths_match(r, paths))])
        if scoped:
            header = ("\n## Regras com escopo (valem nos arquivos tocados)" if paths else
                      "\n## Regras com escopo (aparecem ao tocar os arquivos)")
            if pack.header(header, [r for r in scoped if r.id not in focus_ids]):
                for record in scoped:
                    tag = f"[{record.subtype}] " if record.subtype else ""
                    text = (f"- {tag}{mark(record)}{record.title} — "
                            f"{', '.join(record.scope_paths)}")
                    if not pack.fits(text):
                        if record.id not in focus_ids:
                            pack.omitted.append(record)
                        continue
                    pack.lines.append(text)
                    pack.used += len(text) + 1
                    if record.id not in focus_ids:
                        pack.ids.append(record.id)

        included = list(dict.fromkeys(pack.ids))
        omitted = list({r.id: r for r in pack.omitted if r.id not in included}.values())
        omitted_keys = [r.key or r.id for r in omitted]
        if omitted:
            listed = ", ".join(f"`{k}`" for k in omitted_keys[:OMITTED_LISTED])
            extra = len(omitted) - OMITTED_LISTED
            more = f" e mais {extra}" if extra > 0 else ""
            pack.lines.append(f"\n_{len(omitted)} item(ns) fora do orçamento: {listed}{more}. "
                              "Use item_search ou item_get._")
        pack.lines.append('\n_Detalhe de um item: item_get(keys=[...], repo=".")._')
        brain.count(included, "shown")
        return {
            "linked": True, "repo_key": link["repo_key"], "workspace": link["workspace"],
            "project": link["project"], "markdown": "\n".join(pack.lines),
            "included": len(included), "omitted": len(omitted), "omitted_keys": omitted_keys,
            "sensitive": sensitive,
        }

    @staticmethod
    def _focus_line(text: str, record: ItemRecord) -> str:
        """Item em foco: a linha e o começo do content, para dispensar um item_get depois."""
        body = " ".join((record.content or "").split())
        if body and body != record.summary.strip():
            cut = body[:FOCUS_CONTENT_CHARS] + ("…" if len(body) > FOCUS_CONTENT_CHARS else "")
            text += "\n  > " + cut
        return text

    @staticmethod
    def _secret_line(brain: Brain, record: ItemRecord, mark: str) -> str:
        item = brain.view(record)
        if item.has_value:
            use = f"usar: `knowledge-mcp run --env VAR={item.key or item.id} -- <comando>`"
        else:
            use = f"sem valor — peça ao usuário para preencher em {fill_url(item, brain.cid)}"
        return f"- {mark}**{item.title}** — {item.summary.strip()} · {use}"

