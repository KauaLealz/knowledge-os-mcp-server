"""CLI do segundo cérebro em processo separado, como o hook o chama (plumb-brain T7)."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    return {**os.environ, "KNOWLEDGE_OS_HOME": str(home), "PYTHONPATH": str(ROOT / "src"),
            "LOG_LEVEL": "WARNING"}


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "app"
    (p / ".git").mkdir(parents=True)  # basta para ser projeto (sem remote: chave por caminho)
    return p


def cli(env, *args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "knowledge_os.cli", *args], env=env, cwd=ROOT, input=stdin,
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


def _save(env, project, entries):
    code = (
        "import json,sys\n"
        "from knowledge_os.config import ensure_home, validate_and_init_config\n"
        "ensure_home(); validate_and_init_config()\n"
        "from knowledge_os.services.item_service import ItemService\n"
        "from knowledge_os.services.project_service import ProjectService\n"
        f"link = ProjectService().resolve({str(project)!r})\n"
        "ItemService().save(json.loads(sys.argv[1]), "
        "default_location=(link['workspace_id'], link['domain_id']))\n"
    )
    subprocess.run([sys.executable, "-c", code, json.dumps(entries)], env=env, cwd=ROOT,
                   check=True, capture_output=True, timeout=120)


def test_version(env):
    out = cli(env, "--version")
    assert out.returncode == 0 and out.stdout.startswith("knowledge-mcp ")


def test_link_e_context_markdown(env, project):
    assert cli(env, "link", "--project", str(project), "--workspace", "Polara",
               "--domain", "app").returncode == 0
    _save(env, project, [{"key": "regra/x", "type": "rule", "memory_class": "longterm",
                          "title": "Regra X", "summary": "Sempre X", "content": "..."}])
    out = cli(env, "context", "--project", str(project))
    assert out.returncode == 0
    assert "Polara / app" in out.stdout and "**Regra X**" in out.stdout


def test_hook_claude_e_cursor(env, project):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    claude = cli(env, "context", "--hook", "claude",
                 stdin=json.dumps({"cwd": str(project), "hook_event_name": "SessionStart"}))
    assert claude.stdout.isascii(), "acentos escapados: imune à codepage do Windows"
    payload = json.loads(claude.stdout)["hookSpecificOutput"]
    assert payload["hookEventName"] == "SessionStart" and "W / D" in payload["additionalContext"]
    assert "cérebro" in payload["additionalContext"]
    cursor = cli(env, "context", "--hook", "cursor",
                 stdin="﻿" + json.dumps({"workspace_roots": [str(project)]}))  # BOM do Cursor
    assert "W / D" in json.loads(cursor.stdout)["additional_context"]


def test_hook_fora_de_projeto_fica_em_silencio(env, tmp_path):
    plain = tmp_path / "pasta"
    plain.mkdir()
    if any((p / ".git").exists() for p in plain.parents):
        pytest.skip("pasta temporária está dentro de um repositório git")
    out = cli(env, "context", "--hook", "claude", stdin=json.dumps({"cwd": str(plain)}))
    assert out.returncode == 0 and out.stdout == ""


def test_projeto_nao_ligado_sugere_setup(env, project):
    out = cli(env, "context", "--hook", "claude", stdin=json.dumps({"cwd": str(project)}))
    assert "/plumb-setup" in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def test_falha_vira_aviso_e_nao_quebra_a_sessao(env, project):
    home = Path(env["KNOWLEDGE_OS_HOME"])
    home.mkdir(parents=True)
    (home / "connections.json").write_text("{json quebrado", encoding="utf-8")
    out = cli(env, "context", "--hook", "claude", stdin=json.dumps({"cwd": str(project)}))
    assert out.returncode == 0
    assert "indisponível" in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def _entry(key: str, title: str, **extra) -> str:
    return json.dumps({"key": key, "type": "knowledge", "memory_class": "working",
                       "title": title, "summary": "veio da fila", "content": "...", **extra})


def test_fila_offline_no_home_e_gravada_no_inicio_da_sessao(env, project, tmp_path):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    other = tmp_path / "outro"
    (other / ".git").mkdir(parents=True)
    cli(env, "link", "--project", str(other), "--workspace", "W", "--domain", "Outro")
    queue = Path(env["KNOWLEDGE_OS_HOME"]) / "pending.jsonl"
    queue.write_text(_entry("gotcha/a", "Gravado depois") + "\n"
                     + _entry("gotcha/b", "Do outro projeto", project=str(other)) + "\n",
                     encoding="utf-8")
    out = cli(env, "context", "--project", str(project))
    assert "2 item(ns) da fila offline gravados" in out.stdout
    assert "Gravado depois" in out.stdout and "Do outro projeto" not in out.stdout
    assert "Do outro projeto" in cli(env, "context", "--project", str(other)).stdout
    assert not queue.exists()


def test_fila_antiga_do_projeto_ainda_e_lida(env, project):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    legacy = project / ".plumb" / "pending-brain.jsonl"
    legacy.parent.mkdir()
    legacy.write_text(_entry("gotcha/velha", "Fila antiga") + "\n", encoding="utf-8")
    out = cli(env, "context", "--project", str(project))
    assert "Fila antiga" in out.stdout and not legacy.exists()


def test_mudanca_em_andamento_aparece_e_concluida_some(env, project):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    _save(env, project, [{"key": "mudanca/pay-142", "type": "task", "memory_class": "working",
                          "title": "PAY-142 — Pix no checkout",
                          "summary": "Construindo: falta recusar método inválido",
                          "content": "# PAY-142 ..."}])
    out = cli(env, "context", "--project", str(project)).stdout
    assert "## Mudanças em andamento" in out and "falta recusar método inválido" in out
    _save(env, project, [{"key": "mudanca/pay-142", "status": "done",
                          "summary": "Concluída: Pix devolve QR code"}])
    assert "PAY-142" not in cli(env, "context", "--project", str(project)).stdout


def test_recent_json(env, project):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    _save(env, project, [{"key": "decisao/y", "type": "insight", "memory_class": "working",
                          "title": "Decisão Y", "summary": "porque sim", "content": "...",
                          "source": "PAY-1"}])
    data = json.loads(cli(env, "recent", "--json").stdout)
    assert [(d["title"], d["action"], d["source"], d["status"]) for d in data] == [
        ("Decisão Y", "created", "PAY-1", "active")]


def test_dois_processos_esvaziando_a_mesma_fila_gravam_cada_key_uma_vez(env, project):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    queue = Path(env["KNOWLEDGE_OS_HOME"]) / "pending.jsonl"
    queue.write_text("".join(_entry(f"gotcha/k{i}", f"Item {i}") + "\n" for i in range(50)),
                     encoding="utf-8")
    procs = [subprocess.Popen(
        [sys.executable, "-m", "knowledge_os.cli", "context", "--project", str(project)], env=env,
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        for _ in range(2)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs)
    total = sum(int(m.group(1)) for out, _ in outs
                if (m := re.search(r"(\d+) item\(ns\) da fila", out)))
    assert total == 50
    code = (
        "from knowledge_os.config import ensure_home, validate_and_init_config\n"
        "ensure_home(); validate_and_init_config()\n"
        "from sqlalchemy import select, func\n"
        "from knowledge_os.db.models import Item\n"
        "from knowledge_os.db.session import get_engine, get_session\n"
        "s = get_session(get_engine())\n"
        "print(s.execute(select(func.count(), func.count(func.distinct(Item.key))).where("
        "Item.key.like('gotcha/k%'))).one())\n"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True,
                         text=True, timeout=120, check=True).stdout
    assert out.strip() == "(50, 50)"
    assert not queue.exists() and not list(queue.parent.glob("pending*.claimed"))


def test_linha_acrescentada_durante_a_gravacao_nao_se_perde(env, project, monkeypatch):
    from knowledge_os import cli
    from knowledge_os.services.item_service import ItemService

    cli_env_home = Path(env["KNOWLEDGE_OS_HOME"])
    cli.main(["link", "--project", str(project), "--workspace", "W", "--domain", "D"])
    queue = cli._pending_file()
    queue.write_text(_entry("gotcha/a", "A") + "\n", encoding="utf-8")
    real_save = ItemService.save

    def save_and_append(self, entries, **kw):
        with queue.open("a", encoding="utf-8") as f:  # o agente escreve após a posse
            f.write(_entry("gotcha/nova", "Nova") + "\n")
        return real_save(self, entries, **kw)

    monkeypatch.setattr(ItemService, "save", save_and_append)
    assert cli._flush_file(queue, project)[0] == 1
    assert "gotcha/nova" in queue.read_text(encoding="utf-8")
    assert cli_env_home is not None


def _link_inprocess(project):
    from knowledge_os import cli

    cli.main(["link", "--project", str(project), "--workspace", "W", "--domain", "D"])
    return cli


def test_linha_json_que_nao_e_objeto_vai_para_as_rejeitadas(env, project):
    cli = _link_inprocess(project)
    queue = cli._pending_file()
    queue.write_text("[1, 2]\nnull\n\"texto\"\n" + _entry("gotcha/ok", "Ok") + "\n",
                     encoding="utf-8")
    saved, err = cli._flush_file(queue, project)
    assert saved == 1 and "linha inválida" in err
    assert queue.read_text(encoding="utf-8").splitlines() == ["[1, 2]", "null", '"texto"']
    assert not list(queue.parent.glob("pending*.claimed"))


def test_erro_inesperado_devolve_o_conteudo_a_fila(env, project, monkeypatch):
    cli = _link_inprocess(project)
    queue = cli._pending_file()
    queue.write_text(_entry("gotcha/a", "A") + "\n", encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("estourou")

    monkeypatch.setattr(cli, "_rewrite_claimed", boom)
    saved, err = cli._flush_file(queue, project)
    assert "estourou" in err
    assert "gotcha/a" in queue.read_text(encoding="utf-8")
    assert not list(queue.parent.glob("pending*.claimed"))


def test_rename_negado_vira_erro_visivel(env, project, monkeypatch):
    cli = _link_inprocess(project)
    queue = cli._pending_file()
    queue.write_text(_entry("gotcha/a", "A") + "\n", encoding="utf-8")

    def denied(self, target):
        raise PermissionError("negado")

    monkeypatch.setattr(Path, "rename", denied)
    saved, err = cli._flush_file(queue, project)
    assert saved == 0 and "PermissionError" in err
    assert "gotcha/a" in queue.read_text(encoding="utf-8")


def test_linha_escrita_no_arquivo_tomado_depois_da_leitura_volta_a_fila(env, project,
                                                                         monkeypatch):
    from knowledge_os.services.item_service import ItemService

    cli = _link_inprocess(project)
    queue = cli._pending_file()
    queue.write_text(_entry("gotcha/a", "A") + "\n", encoding="utf-8")
    real_save = ItemService.save

    def save_and_append(self, entries, **kw):
        claimed = next(queue.parent.glob("pending.*.claimed"))
        with claimed.open("a", encoding="utf-8") as f:  # escritor com o arquivo já aberto
            f.write(_entry("gotcha/tarde", "Tarde") + "\n")
        return real_save(self, entries, **kw)

    monkeypatch.setattr(ItemService, "save", save_and_append)
    assert cli._flush_file(queue, project)[0] == 1
    assert "gotcha/tarde" in queue.read_text(encoding="utf-8")
    assert not list(queue.parent.glob("pending*.claimed"))


def test_crash_depois_de_gravar_um_grupo_nao_reprocessa_o_grupo(env, project, tmp_path,
                                                                 monkeypatch):
    from knowledge_os.services.item_service import ItemService

    cli = _link_inprocess(project)
    other = tmp_path / "outro"
    (other / ".git").mkdir(parents=True)
    cli.main(["link", "--project", str(other), "--workspace", "W", "--domain", "Outro"])
    queue = cli._pending_file()
    queue.write_text(_entry("gotcha/a", "A") + "\n"
                     + _entry("gotcha/b", "B", project=str(other)) + "\n", encoding="utf-8")
    real_save = ItemService.save
    calls = []

    def save_then_die(self, entries, **kw):
        if calls:
            raise SystemExit("morreu")
        calls.append(1)
        return real_save(self, entries, **kw)

    monkeypatch.setattr(ItemService, "save", save_then_die)
    with pytest.raises(SystemExit):
        cli._flush_file(queue, project)
    left = next(queue.parent.glob("pending.*.claimed")).read_text(encoding="utf-8")
    assert "gotcha/b" in left and "gotcha/a" not in left


def test_backup_pela_cli_gera_arquivo_que_abre(env, project):
    import sqlite3

    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    out = cli(env, "backup")
    assert out.returncode == 0, out.stderr
    files = list((Path(env["KNOWLEDGE_OS_HOME"]) / "backups").glob("knowledge-*.db"))
    assert len(files) == 1
    conn = sqlite3.connect(files[0])
    try:
        assert conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] >= 1
    finally:
        conn.close()
