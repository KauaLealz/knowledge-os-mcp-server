"""CLI do segundo cérebro em processo separado, como o hook o chama (plumb-brain T7)."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _connections(home: Path, data: Path) -> None:
    """connections.json do processo filho: uma conexão padrão sobre `data`."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "connections.json").write_text(json.dumps({
        "version": "1.0", "default": "dados",
        "connections": [{"id": "dados", "name": "Dados", "path": str(data)}],
    }), encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    _connections(home, tmp_path / "dados")
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
        "from knowledge_os.services.item_service import ItemService\n"
        "from knowledge_os.services.repo_service import RepoService\n"
        f"link = RepoService().resolve({str(project)!r})\n"
        "ItemService().save(json.loads(sys.argv[1]), "
        "default_location=(link['workspace'], link['project']))\n"
    )
    subprocess.run([sys.executable, "-c", code, json.dumps(entries)], env=env, cwd=ROOT,
                   check=True, capture_output=True, timeout=120)


def test_version(env):
    out = cli(env, "--version")
    assert out.returncode == 0 and out.stdout.startswith("knowledge-mcp ")


def test_link_e_context_markdown(env, project):
    assert cli(env, "link", "--repo", str(project), "--workspace", "Polara",
               "--project", "app").returncode == 0
    _save(env, project, [{"key": "rule/x", "type": "rule", "subtype": "code",
                          "title": "Regra X", "summary": "Sempre X", "content": "..."}])
    out = cli(env, "context", "--repo", str(project))
    assert out.returncode == 0
    assert "Polara / app" in out.stdout and "[code] **Regra X**" in out.stdout


def test_hook_claude_e_cursor(env, project):
    cli(env, "link", "--repo", str(project), "--workspace", "W", "--project", "D")
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
    text = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "/plumb-setup" in text and 'repo(action="link"' in text


def test_sem_conexao_o_hook_diz_como_criar(env, project):
    (Path(env["KNOWLEDGE_OS_HOME"]) / "connections.json").unlink()
    out = cli(env, "context", "--hook", "claude", stdin=json.dumps({"cwd": str(project)}))
    assert out.returncode == 0
    text = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Nenhuma conexão configurada" in text and "connection_create" in text
    assert not (Path(env["KNOWLEDGE_OS_HOME"]) / "connections.json").exists()


def test_falha_vira_aviso_e_nao_quebra_a_sessao(env, project):
    home = Path(env["KNOWLEDGE_OS_HOME"])
    (home / "connections.json").write_text("{json quebrado", encoding="utf-8")
    out = cli(env, "context", "--hook", "claude", stdin=json.dumps({"cwd": str(project)}))
    assert out.returncode == 0
    assert "indisponível" in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def _entry(key: str, title: str, **extra) -> str:
    return json.dumps({"key": key, "type": "howto", "title": title, "summary": "veio da fila",
                       "content": "...", **extra})


def test_fila_offline_no_home_e_gravada_no_inicio_da_sessao(env, project, tmp_path):
    cli(env, "link", "--repo", str(project), "--workspace", "W", "--project", "D")
    other = tmp_path / "outro"
    (other / ".git").mkdir(parents=True)
    cli(env, "link", "--repo", str(other), "--workspace", "W", "--project", "Outro")
    queue = Path(env["KNOWLEDGE_OS_HOME"]) / "pending.jsonl"
    queue.write_text(_entry("gotcha/a", "Gravado depois") + "\n"
                     + _entry("gotcha/b", "Do outro projeto", repo=str(other)) + "\n",
                     encoding="utf-8")
    out = cli(env, "context", "--repo", str(project))
    assert "2 item(ns) da fila offline gravados" in out.stdout
    assert "Gravado depois" in out.stdout and "Do outro projeto" not in out.stdout
    assert "Do outro projeto" in cli(env, "context", "--repo", str(other)).stdout
    assert not queue.exists()


def test_entrada_no_formato_antigo_sai_da_fila_para_as_rejeitadas(env, conn, project):
    cli = _link_inprocess(project)
    queue = cli._pending_file()
    old = {"key": "gotcha/velha", "type": "knowledge", "memory_class": "working",
           "title": "Formato antigo", "summary": "s", "content": "c"}
    queue.write_text(json.dumps(old) + "\n", encoding="utf-8")
    saved, err = cli._flush_file(queue, project)
    assert saved == 0 and "1 entrada(s) inválida(s)" in err
    assert not queue.exists() or not queue.read_text(encoding="utf-8").strip()
    rejected = queue.with_name("pending.rejected.jsonl").read_text(encoding="utf-8")
    row = json.loads(rejected.splitlines()[0])
    assert row["entry"]["key"] == "gotcha/velha" and "memory_class" in row["error"]
    assert not list(queue.parent.glob("pending*.claimed"))


def test_fila_envenenada_grava_as_boas_e_rejeita_a_antiga(env, conn, project):
    from knowledge_os.services.brain import Brain

    cli = _link_inprocess(project)
    queue = cli._pending_file()
    old = json.dumps({"key": "gotcha/velha", "type": "howto", "memory_class": "longterm",
                      "title": "Antiga", "summary": "s", "content": "c"})
    queue.write_text(_entry("gotcha/a", "A") + "\n" + old + "\n" + _entry("gotcha/b", "B")
                     + "\n" + _entry("gotcha/c", "C") + "\n", encoding="utf-8")
    saved, err = cli._flush_file(queue, project)
    assert saved == 3
    assert "1 entrada(s) inválida(s)" in err and "pending.rejected.jsonl" in err
    keys = {r.key for r in Brain().snapshot.records.values()}
    assert {"gotcha/a", "gotcha/b", "gotcha/c"} <= keys and "gotcha/velha" not in keys
    assert not queue.exists() or not queue.read_text(encoding="utf-8").strip()
    lines = queue.with_name("pending.rejected.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(ln)["entry"]["key"] for ln in lines] == ["gotcha/velha"]
    assert cli._flush_file(queue, project) == (0, None)  # a próxima sessão não tropeça nela


def test_hook_claude_com_o_pacote_v2(env, project):
    cli(env, "link", "--repo", str(project), "--workspace", "W", "--project", "D")
    _save(env, project, [{"key": "rule/sec", "type": "rule", "subtype": "security",
                          "title": "Nada de log de cartao", "summary": "PCI",
                          "content": "c"}])
    out = cli(env, "context", "--hook", "claude",
              stdin=json.dumps({"cwd": str(project), "hook_event_name": "SessionStart"}))
    assert out.returncode == 0
    payload = json.loads(out.stdout)["hookSpecificOutput"]
    assert payload["hookEventName"] == "SessionStart"
    assert "## Segurança" in payload["additionalContext"]
    assert "Nada de log de cartao" in payload["additionalContext"]


def test_fila_antiga_do_projeto_ainda_e_lida(env, project):
    cli(env, "link", "--repo", str(project), "--workspace", "W", "--project", "D")
    legacy = project / ".plumb" / "pending-brain.jsonl"
    legacy.parent.mkdir()
    legacy.write_text(_entry("gotcha/velha", "Fila antiga") + "\n", encoding="utf-8")
    out = cli(env, "context", "--repo", str(project))
    assert "Fila antiga" in out.stdout and not legacy.exists()


def test_recent_json(env, project):
    cli(env, "link", "--repo", str(project), "--workspace", "W", "--project", "D")
    _save(env, project, [{"key": "rule/y", "type": "rule", "subtype": "decision",
                          "title": "Decisão Y", "summary": "porque sim",
                          "content": "## Por quê\nx\n## Alternativa descartada\ny",
                          "source": "PAY-1"}])
    data = json.loads(cli(env, "recent", "--json").stdout)
    assert [(d["title"], d["action"], d["source"], d["status"], d["subtype"], d["origin"])
            for d in data] == [("Decisão Y", "created", "PAY-1", "active", "decision", "agent")]
    assert "memory_class" not in data[0]
    text = cli(env, "recent").stdout
    assert "rule/decision" in text and "Decisão Y" in text


def test_dois_processos_esvaziando_a_mesma_fila_gravam_cada_key_uma_vez(env, project):
    cli(env, "link", "--repo", str(project), "--workspace", "W", "--project", "D")
    queue = Path(env["KNOWLEDGE_OS_HOME"]) / "pending.jsonl"
    queue.write_text("".join(_entry(f"gotcha/k{i}", f"Item {i}") + "\n" for i in range(50)),
                     encoding="utf-8")
    procs = [subprocess.Popen(
        [sys.executable, "-m", "knowledge_os.cli", "context", "--repo", str(project)], env=env,
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        for _ in range(2)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs)
    total = sum(int(m.group(1)) for out, _ in outs
                if (m := re.search(r"(\d+) item\(ns\) da fila", out)))
    assert total == 50
    code = (
        "from knowledge_os.services.brain import Brain\n"
        "keys = [r.key for r in Brain().snapshot.records.values()\n"
        "        if (r.key or '').startswith('gotcha/k')]\n"
        "print((len(keys), len(set(keys))))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True,
                         text=True, timeout=120, check=True).stdout
    assert out.strip() == "(50, 50)"
    assert not queue.exists() and not list(queue.parent.glob("pending*.claimed"))


def test_linha_acrescentada_durante_a_gravacao_nao_se_perde(env, conn, project, monkeypatch):
    from knowledge_os import cli
    from knowledge_os.services.item_service import ItemService

    cli_env_home = Path(env["KNOWLEDGE_OS_HOME"])
    cli.main(["link", "--repo", str(project), "--workspace", "W", "--project", "D"])
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

    cli.main(["link", "--repo", str(project), "--workspace", "W", "--project", "D"])
    return cli


def test_linha_json_que_nao_e_objeto_vai_para_as_rejeitadas(env, conn, project):
    cli = _link_inprocess(project)
    queue = cli._pending_file()
    queue.write_text("[1, 2]\nnull\n\"texto\"\n" + _entry("gotcha/ok", "Ok") + "\n",
                     encoding="utf-8")
    saved, err = cli._flush_file(queue, project)
    assert saved == 1 and "linha inválida" in err
    assert queue.read_text(encoding="utf-8").splitlines() == ["[1, 2]", "null", '"texto"']
    assert not list(queue.parent.glob("pending*.claimed"))


def test_erro_inesperado_devolve_o_conteudo_a_fila(env, conn, project, monkeypatch):
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


def test_rename_negado_vira_erro_visivel(env, conn, project, monkeypatch):
    cli = _link_inprocess(project)
    queue = cli._pending_file()
    queue.write_text(_entry("gotcha/a", "A") + "\n", encoding="utf-8")

    def denied(self, target):
        raise PermissionError("negado")

    monkeypatch.setattr(Path, "rename", denied)
    saved, err = cli._flush_file(queue, project)
    assert saved == 0 and "PermissionError" in err
    assert "gotcha/a" in queue.read_text(encoding="utf-8")


def test_linha_escrita_no_arquivo_tomado_depois_da_leitura_volta_a_fila(env, conn, project,
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


def test_crash_depois_de_gravar_um_grupo_nao_reprocessa_o_grupo(env, conn, project, tmp_path,
                                                                 monkeypatch):
    from knowledge_os.services.item_service import ItemService

    cli = _link_inprocess(project)
    other = tmp_path / "outro"
    (other / ".git").mkdir(parents=True)
    cli.main(["link", "--repo", str(other), "--workspace", "W", "--project", "Outro"])
    queue = cli._pending_file()
    queue.write_text(_entry("gotcha/a", "A") + "\n"
                     + _entry("gotcha/b", "B", repo=str(other)) + "\n", encoding="utf-8")
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


def test_comando_de_copia_de_seguranca_saiu(env):
    out = cli(env, "backup")
    assert out.returncode != 0  # o git é o histórico


def test_context_aceita_a_chave_remota_como_project(env, project):
    subprocess.run(["git", "-C", str(project), "init", "-q"], capture_output=True)
    cli(env, "link", "--repo", "github.com/org/app", "--workspace", "Org", "--project", "app")
    out = cli(env, "context", "--repo", "github.com/org/app")
    assert out.returncode == 0 and "Org / app" in out.stdout
