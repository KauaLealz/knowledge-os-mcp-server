"""Ponto de entrada do `knowledge-mcp`.

Os subcomandos do segundo cérebro (`context`, `recent`, `pending`, `link`) rodam sem carregar
o fastmcp: o hook de início de sessão chama `context` em toda sessão e precisa ser rápido.
O resto (servidor MCP via stdio, `ui`, `--check-db`, `--bootstrap`) delega ao `knowledge_os.main`.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from knowledge_os import __version__

BRAIN_COMMANDS = ("context", "recent", "pending", "link", "backup", "run")
PENDING_NAME = "pending.jsonl"  # no home do cérebro, fora de qualquer repositório
LEGACY_PENDING = Path(".plumb") / "pending-brain.jsonl"  # versões antigas do Plumb
HOOK_BUDGET = 1200


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="knowledge-mcp", description="Segundo cérebro (Knowledge OS)")
    sub = p.add_subparsers(dest="command", required=True)

    ctx = sub.add_parser("context", help="pacote de contexto do projeto (Markdown)")
    ctx.add_argument("--repo", default=".", help="pasta do projeto (padrão: atual)")
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
    pen.add_argument("--repo", default=".", help="pasta do projeto (padrão: atual)")

    sub.add_parser("backup", help="copia consistente do banco SQLite em <home>/backups")

    lnk = sub.add_parser("link", help="liga o projeto a um workspace/domain")
    lnk.add_argument("--repo", default=".")
    lnk.add_argument("--workspace",
                     help="padrão: o de outro repo do mesmo dono já ligado, ou o nome do dono")
    lnk.add_argument("--domain", help="padrão: o nome do repositório")

    run = sub.add_parser(
        "run", help="roda um comando com segredos do cérebro, sem shell, com a saída redigida",
        description="Ex.: knowledge-mcp run --env NPM_TOKEN=segredo/npm-token -- npm publish",
    )
    run.add_argument("--env", action="append", default=[], metavar="VAR=segredo/<nome>",
                     help="variável de ambiente do comando com o valor do segredo (repetível)")
    run.add_argument("--stdin", metavar="segredo/<nome>",
                     help="entrega o valor no stdin (ex.: docker login --password-stdin)")
    run.add_argument("--repo", default=".", help="pasta do projeto (padrão: atual)")
    run.add_argument("cmd", nargs=argparse.REMAINDER, help="-- comando e argumentos")
    return p


def _init() -> None:
    from knowledge_os.config import ensure_home, validate_and_init_config

    ensure_home()
    validate_and_init_config()


def _pending_file() -> Path:
    from knowledge_os.config import KNOWLEDGE_HOME

    return KNOWLEDGE_HOME / PENDING_NAME


ORPHAN_AFTER_S = 600  # `.claimed` abandonado (processo morreu no meio) é reprocessado depois disso


def _claim(src: Path, base: Path) -> Path | None:
    """Toma posse de `src` renomeando-o (atômico): só um processo vence.

    None se perdeu a corrida (o arquivo sumiu: outro processo tomou). Outro erro de
    rename (permissão, arquivo aberto por um escritor) sobe para quem chama reportar.
    """
    claimed = base.with_name(f"{base.stem}.{os.getpid()}-{time.time_ns()}.claimed")
    try:
        src.rename(claimed)
    except FileNotFoundError:
        return None
    try:
        os.utime(claimed)  # a idade de um `.claimed` conta a partir da posse, não da última linha
    except OSError:
        pass
    return claimed


def _claimed_files(path: Path) -> tuple[list[Path], list[str]]:
    """Fila do arquivo mais `.claimed` órfãos, já tomados por este processo (e os erros)."""
    found: list[Path] = []
    errors: list[str] = []
    candidates: list[Path] = []
    if path.exists():
        candidates.append(path)
    now = time.time()
    for orphan in path.parent.glob(f"{path.stem}.*.claimed"):
        try:
            if now - orphan.stat().st_mtime > ORPHAN_AFTER_S:
                candidates.append(orphan)
        except OSError:
            continue
    for src in candidates:
        try:
            if mine := _claim(src, path):
                found.append(mine)
        except OSError as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return found, errors


def _requeue(queue: Path, lines: list[str]) -> None:
    if lines:
        with queue.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def _flush_file(path: Path, repo: Path) -> tuple[int, str | None]:
    """Grava uma fila (uma entrada de item_save por linha, com `repo` opcional).

    A fila é tomada por rename antes de ler: duas sessões abrindo juntas não processam as
    mesmas linhas, e o que o agente acrescentar depois cai num arquivo novo. Entradas sem
    `repo` vão para o projeto da sessão. O que falhar volta para a fila.
    """
    claimed_files, errors = _claimed_files(path)
    saved = 0
    for claimed in claimed_files:
        try:
            n, err = _flush_claimed(claimed, path, repo)
        except Exception as exc:  # noqa: BLE001 - nunca deixar um `.claimed` órfão quebrar a sessão
            n, err = 0, f"{type(exc).__name__}: {exc}"
            try:
                _requeue(path, [ln for ln in claimed.read_text(encoding="utf-8").splitlines()
                                if ln.strip()])
                claimed.unlink(missing_ok=True)
            except OSError:
                pass  # fica como `.claimed`; é reprocessado quando envelhecer
        saved += n
        if err:
            errors.append(err)
    return saved, "; ".join(errors) or None


def _rewrite_claimed(claimed: Path, lines: list[str], read_size: int) -> int:
    """Reescreve o `.claimed` só com `lines` + o que foi acrescentado depois da leitura.

    Devolve o novo tamanho da parte já lida.
    """
    head = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    tmp = claimed.with_suffix(".tmp")
    tmp.write_bytes(head + claimed.read_bytes()[read_size:])
    os.replace(tmp, claimed)
    return len(head)


def _flush_claimed(claimed: Path, queue: Path, repo: Path) -> tuple[int, str | None]:
    from knowledge_os.services.item_service import ItemService
    from knowledge_os.services.repo_service import RepoService

    raw = claimed.read_bytes()
    read_size = len(raw)
    lines = [ln for ln in raw.decode("utf-8").splitlines() if ln.strip()]
    groups: dict[str, list[tuple[dict[str, Any], str]]] = {}
    saved, errors, invalid = 0, [], []
    for ln in lines:
        try:
            entry = json.loads(ln)
        except ValueError:
            entry = None
        if not isinstance(entry, dict):
            errors.append("linha inválida na fila")
            invalid.append(ln)
            continue
        groups.setdefault(entry.pop("repo", None) or str(repo), []).append((entry, ln))
    _requeue(queue, invalid)
    pending = {proj: [ln for _, ln in items] for proj, items in groups.items()}
    if invalid:
        read_size = _rewrite_claimed(claimed, [ln for v in pending.values() for ln in v],
                                     read_size)
    for proj, items in groups.items():
        entries = [e for e, _ in items]
        try:
            link = RepoService().resolve(proj)
            default = (link["workspace_id"], link["domain_id"]) if link else None
            ItemService().save(entries, default_location=default)
            saved += len(entries)
        except Exception as exc:  # noqa: BLE001 - a fila fica para a próxima tentativa
            errors.append(f"{type(exc).__name__}: {exc}")
            _requeue(queue, [json.dumps({**e, "repo": proj}, ensure_ascii=False)
                             for e in entries])
        del pending[proj]
        read_size = _rewrite_claimed(claimed, [ln for v in pending.values() for ln in v],
                                     read_size)
    late = claimed.read_bytes()[read_size:]  # acrescentado ao arquivo tomado após a leitura
    if late:
        _requeue(queue, late.decode("utf-8").splitlines())
    claimed.unlink(missing_ok=True)
    return saved, "; ".join(errors) or None


def _flush_pending(repo: Path) -> tuple[int, str | None]:
    """Grava a fila offline do cérebro (no home) e a fila antiga do projeto, se existir."""
    total, error = 0, None
    for path in (_pending_file(), repo / LEGACY_PENDING):
        n, err = _flush_file(path, repo)
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
    target = str(hook_input.get("cwd") or (roots[0] if roots else None) or args.repo)
    repo = Path(target)  # caminho para a fila e para detectar repo; a chave usa o texto
    budget = args.budget if not args.hook else min(args.budget, HOOK_BUDGET)

    try:
        _init()
        flushed, flush_error = _flush_pending(repo.resolve())
        from knowledge_os.services.context_service import ContextService

        out = ContextService().build(target, args.paths, args.query, budget)
        text = out["markdown"]
        if not out["linked"] and args.hook and not _is_project(repo.resolve()):
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
            f"item_save por linha, com \"repo\": caminho do repositório)._"
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

    from knowledge_os.db.models import Domain, Item, Workspace
    from knowledge_os.db.session import get_engine, get_session

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
    count, error = _flush_pending(Path(args.repo).resolve())
    if error:
        print(f"Fila não gravada: {error}", file=sys.stderr)
        return 1
    print(f"{count} item(ns) gravados" if count else "Fila vazia")
    return 0


def _link(args: argparse.Namespace) -> int:
    _init()
    from knowledge_os.services.repo_service import RepoService

    print(json.dumps(RepoService().link(args.repo, args.workspace, args.domain)))
    return 0


def _backup(args: argparse.Namespace) -> int:
    _init()
    from knowledge_os.services.maintenance import backup

    path = backup("manual")
    print(path if path else "Backup automático só para SQLite; este banco não é suportado.")
    return 0 if path else 1


def _run(args: argparse.Namespace) -> int:
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        print("Erro: informe o comando depois de --", file=sys.stderr)
        return 1
    pairs = []
    for spec in args.env:
        var, sep, key = spec.partition("=")
        if not sep or not var or not key:
            print(f"Erro: --env espera VAR=segredo/<nome>, recebi {spec!r}", file=sys.stderr)
            return 1
        pairs.append((var, key))
    if not pairs and not args.stdin:
        print("Erro: informe --env VAR=segredo/<nome> ou --stdin segredo/<nome>", file=sys.stderr)
        return 1
    _init()
    from knowledge_os.services.secret_run import run
    from knowledge_os.services.secret_service import SecretService

    secrets = SecretService()
    values = {var: secrets.resolve(args.repo, key)[1] for var, key in pairs}
    stdin_value = secrets.resolve(args.repo, args.stdin)[1] if args.stdin else None
    return run(cmd, values, stdin_value)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--version"]:
        print(f"knowledge-mcp {__version__}")
        return 0
    if not argv or argv[0] not in BRAIN_COMMANDS:
        from knowledge_os.main import main as server_main

        return server_main(argv)
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = _parser().parse_args(argv)
    try:
        return {"context": _context, "recent": _recent, "pending": _pending,
                "link": _link, "backup": _backup, "run": _run}[args.command](args)
    except Exception as exc:  # noqa: BLE001
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
