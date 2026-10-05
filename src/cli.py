"""Ponto de entrada do `knowledge-mcp`.

Os subcomandos do segundo cérebro (`context`, `recent`, `pending`, `link`) rodam sem carregar
o fastmcp: o hook de início de sessão chama `context` em toda sessão e precisa ser rápido.
O resto (servidor MCP via stdio, `ui`, `--check-db`, `--bootstrap`) delega ao `src.main`.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src import __version__

BRAIN_COMMANDS = ("context", "recent", "pending", "link")
PENDING_NAME = "pending.jsonl"  # no home do cérebro, fora de qualquer repositório
LEGACY_PENDING = Path(".plumb") / "pending-brain.jsonl"  # versões antigas do Plumb
HOOK_BUDGET = 1200


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="knowledge-mcp", description="Segundo cérebro (Knowledge OS)")
    sub = p.add_subparsers(dest="command", required=True)

    ctx = sub.add_parser("context", help="pacote de contexto do projeto (Markdown)")
    ctx.add_argument("--project", default=".", help="pasta do projeto (padrão: atual)")
    ctx.add_argument("--paths", nargs="*", default=[], help="arquivos tocados (regras com escopo)")
    ctx.add_argument("--query", help="traz também itens relacionados a este texto")
    ctx.add_argument("--budget", type=int, default=1500, help="orçamento em tokens")
    ctx.add_argument("--hook", choices=("claude", "cursor"),
                     help="lê o JSON do hook no stdin e responde no formato da ferramenta")

    rec = sub.add_parser("recent", help="itens criados/alterados desde uma data")
    rec.add_argument("--since", help="AAAA-MM-DD ou ISO (padrão: ontem 00:00)")
    rec.add_argument("--until", help="AAAA-MM-DD ou ISO (padrão: agora)")
    rec.add_argument("--json", action="store_true", help="saída em JSON")

    pen = sub.add_parser("pending", help="grava a fila offline (<home>/pending.jsonl)")
    pen.add_argument("--project", default=".", help="pasta do projeto (padrão: atual)")

    lnk = sub.add_parser("link", help="liga o projeto a um workspace/domain")
    lnk.add_argument("--project", default=".")
    lnk.add_argument("--workspace", help="padrão: o nome do repositório")
    lnk.add_argument("--domain", help="padrão: Geral")
    return p


def _init() -> None:
    from src.config import ensure_home, validate_and_init_config

    ensure_home()
    validate_and_init_config()


def _pending_file() -> Path:
    from src.config import KNOWLEDGE_HOME

    return KNOWLEDGE_HOME / PENDING_NAME


def _flush_file(path: Path, project: Path) -> tuple[int, str | None]:
    """Grava uma fila (uma entrada de item_save por linha, com `project` opcional).

    Entradas sem `project` vão para o projeto da sessão. O que falhar continua no arquivo.
    """
    from src.services.item_service import ItemService
    from src.services.project_service import ProjectService

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    groups: dict[str, list[dict[str, Any]]] = {}
    for ln in lines:
        entry = json.loads(ln)
        groups.setdefault(entry.pop("project", None) or str(project), []).append(entry)
    saved, errors, left = 0, [], []
    for proj, entries in groups.items():
        try:
            link = ProjectService().resolve(proj)
            default = (link["workspace_id"], link["domain_id"]) if link else None
            ItemService().save(entries, default_location=default)
            saved += len(entries)
        except Exception as exc:  # noqa: BLE001 - a fila fica para a próxima tentativa
            errors.append(f"{type(exc).__name__}: {exc}")
            left += [json.dumps({**e, "project": proj}, ensure_ascii=False) for e in entries]
    if left:
        path.write_text("\n".join(left) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return saved, "; ".join(errors) or None


def _flush_pending(project: Path) -> tuple[int, str | None]:
    """Grava a fila offline do cérebro (no home) e a fila antiga do projeto, se existir."""
    total, error = 0, None
    for path in (_pending_file(), project / LEGACY_PENDING):
        if path.exists():
            n, err = _flush_file(path, project)
            total, error = total + n, error or err
    return total, error


def _is_project(path: Path) -> bool:
    return any((p / ".git").exists() for p in (path, *path.parents))


def _context(args: argparse.Namespace) -> int:
    hook_input: dict[str, Any] = {}
    if args.hook:
        try:
            # Bytes + utf-8-sig: o Cursor no Windows manda o JSON do hook em UTF-8 com BOM, e o
            # stdin de texto usaria a codepage local (caminhos com acento quebrariam).
            hook_input = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
        except ValueError:
            hook_input = {}
    roots = hook_input.get("workspace_roots") or []
    project = Path(hook_input.get("cwd") or (roots[0] if roots else None) or args.project)
    budget = args.budget if not args.hook else min(args.budget, HOOK_BUDGET)

    try:
        _init()
        flushed, flush_error = _flush_pending(project.resolve())
        from src.services.context_service import ContextService

        out = ContextService().build(str(project), args.paths, args.query, budget)
        text = out["markdown"]
        if not out["linked"] and args.hook and not _is_project(project.resolve()):
            return 0  # pasta que não é projeto: sem ruído na sessão
        if flushed:
            text += f"\n\n_{flushed} item(ns) da fila offline gravados._"
        if flush_error:
            text += (f"\n\n_Fila offline não gravada ({flush_error}); "
                     f"continua em {_pending_file()}._")
    except Exception as exc:  # noqa: BLE001 - hook nunca pode quebrar a sessão
        text = (
            f"_Segundo cérebro indisponível ({type(exc).__name__}). Siga o trabalho e avise o "
            f"usuário; grave o que for durável em {_pending_file().as_posix()} (uma entrada de "
            f"item_save por linha, com \"project\": caminho do repositório)._"
        )

    # JSON só em ASCII (acentos como \uXXXX): no Windows a ferramenta pode ler a saída do hook
    # numa codepage local e corromper o UTF-8.
    if args.hook == "claude":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": text}}))
    elif args.hook == "cursor":
        print(json.dumps({"additional_context": text}))
    else:
        print(text)
    return 0


def _parse_when(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    return datetime.fromisoformat(value)


def _recent(args: argparse.Namespace) -> int:
    _init()
    from sqlalchemy import select

    from src.db.models import Domain, Item, Workspace
    from src.db.session import get_engine, get_session

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since = _parse_when(args.since, today - timedelta(days=1))
    until = _parse_when(args.until, datetime.now())
    # O banco grava em UTC (utcnow); a janela vem em hora local.
    offset = datetime.now(timezone.utc).replace(tzinfo=None) - datetime.now()
    since_utc, until_utc = since + offset, until + offset
    session = get_session(get_engine())
    try:
        rows = session.execute(
            select(Item, Workspace.name, Domain.name)
            .join(Workspace, Workspace.id == Item.workspace_id)
            .join(Domain, Domain.id == Item.domain_id)
            .where(Item.updated_at >= since_utc, Item.updated_at < until_utc)
            .order_by(Item.updated_at)
        ).all()
    finally:
        session.close()
    data = [
        {
            "action": "created" if item.created_at and item.created_at >= since_utc else "updated",
            "workspace": ws, "domain": dm, "key": item.key, "type": item.type,
            "memory_class": item.memory_class, "title": item.title, "summary": item.summary,
            "source": item.source, "status": item.status,
        }
        for item, ws, dm in rows
    ]
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif not data:
        print("(nenhum item novo ou alterado)")
    else:
        for d in data:
            src = f" [{d['source']}]" if d["source"] else ""
            print(f"- {d['action']} · {d['workspace']}/{d['domain']} · {d['type']} · "
                  f"{d['title']} — {d['summary']}{src}")
    return 0


def _pending(args: argparse.Namespace) -> int:
    _init()
    count, error = _flush_pending(Path(args.project).resolve())
    if error:
        print(f"Fila não gravada: {error}", file=sys.stderr)
        return 1
    print(f"{count} item(ns) gravados" if count else "Fila vazia")
    return 0


def _link(args: argparse.Namespace) -> int:
    _init()
    from src.services.project_service import ProjectService

    print(json.dumps(ProjectService().link(args.project, args.workspace, args.domain)))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--version"]:
        print(f"knowledge-mcp {__version__}")
        return 0
    if not argv or argv[0] not in BRAIN_COMMANDS:
        from src.main import main as server_main

        return server_main(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = _parser().parse_args(argv)
    try:
        return {"context": _context, "recent": _recent, "pending": _pending,
                "link": _link}[args.command](args)
    except Exception as exc:  # noqa: BLE001
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
