"""CLI do segundo cérebro em processo separado, como o hook o chama (plumb-brain T7)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    return {**os.environ, "KNOWLEDGE_OS_HOME": str(home), "PYTHONPATH": str(ROOT),
            "LOG_LEVEL": "WARNING"}


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "app"
    (p / ".git").mkdir(parents=True)  # basta para ser projeto (sem remote: chave por caminho)
    return p


def cli(env, *args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args], env=env, cwd=ROOT, input=stdin,
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


def _save(env, project, entries):
    code = (
        "import json,sys\n"
        "from src.config import ensure_home, validate_and_init_config\n"
        "ensure_home(); validate_and_init_config()\n"
        "from src.services.item_service import ItemService\n"
        "from src.services.project_service import ProjectService\n"
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
    payload = json.loads(claude.stdout)["hookSpecificOutput"]
    assert payload["hookEventName"] == "SessionStart" and "W / D" in payload["additionalContext"]
    cursor = cli(env, "context", "--hook", "cursor",
                 stdin=json.dumps({"workspace_roots": [str(project)]}))
    assert "W / D" in json.loads(cursor.stdout)["additional_context"]


def test_hook_fora_de_projeto_fica_em_silencio(env, tmp_path):
    plain = tmp_path / "pasta"
    plain.mkdir()
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


def test_fila_offline_e_gravada_no_inicio_da_sessao(env, project):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    queue = project / ".plumb" / "pending-brain.jsonl"
    queue.parent.mkdir()
    queue.write_text(json.dumps({"key": "gotcha/offline", "type": "knowledge",
                                 "memory_class": "working", "title": "Gravado depois",
                                 "summary": "veio da fila", "content": "..."}) + "\n",
                     encoding="utf-8")
    out = cli(env, "context", "--project", str(project))
    assert "1 item(ns) da fila offline gravados" in out.stdout
    assert "Gravado depois" in out.stdout and not queue.exists()


def test_recent_json(env, project):
    cli(env, "link", "--project", str(project), "--workspace", "W", "--domain", "D")
    _save(env, project, [{"key": "decisao/y", "type": "insight", "memory_class": "working",
                          "title": "Decisão Y", "summary": "porque sim", "content": "...",
                          "source": "PAY-1"}])
    data = json.loads(cli(env, "recent", "--json").stdout)
    assert [(d["title"], d["action"], d["source"]) for d in data] == [
        ("Decisão Y", "created", "PAY-1")]
