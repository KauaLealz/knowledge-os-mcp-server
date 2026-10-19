import json
import shutil
import subprocess

from knowledge_os.config import ConfigManager
from knowledge_os.services.connection_service import ConnectionService


def _bare_repo(tmp_path, name="remote.git"):
    """Repositório git bare local: um remote de verdade, clonável sem rede."""
    path = tmp_path / name
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)
    return str(path)


_counter = iter(range(10_000))


def _create(client, tmp_path, name="extra", **over):
    """Cria pela camada de serviço (como a ferramenta MCP): a API não cria conexão."""
    path = tmp_path / f"repo-{next(_counter)}"
    path.mkdir()
    conn = ConnectionService().create(name, str(path), **over)
    return client.get(f"/api/connections/{conn.id}")


def test_list_mostra_a_padrao(client, tmp_path):
    r = client.get("/api/connections")
    assert r.status_code == 200
    (c,) = r.json()
    assert c["id"] == "teste" and c["is_default"] is True and "is_catalog" not in c
    assert c["remote_url"] is None and c["last_test"] is None


def test_api_nao_cria_conexao(client, tmp_path):
    """A criação é só pelo MCP (connection_create): POST /api/connections não existe."""
    path = tmp_path / "nova"
    path.mkdir()
    r = client.post("/api/connections", json={"name": "nova", "path": str(path)})
    assert r.status_code == 405
    assert [c["id"] for c in client.get("/api/connections").json()] == ["teste"]


def test_list_mostra_path_e_estado_da_pasta(client, tmp_path):
    c = _create(client, tmp_path).json()
    rows = {x["id"]: x for x in client.get("/api/connections").json()}
    row = rows[c["id"]]
    assert row["path"] and row["path"] == c["path"]
    assert row["path_exists"] is True and row["is_git_repo"] is True


def test_list_marca_pasta_que_sumiu(client, tmp_path):
    c = _create(client, tmp_path).json()
    shutil.rmtree(c["path"], ignore_errors=True)
    row = client.get(f"/api/connections/{c['id']}").json()
    assert row["path_exists"] is False and row["is_git_repo"] is False


def test_get_missing_is_404(client, tmp_path):
    assert client.get("/api/connections/nope").status_code == 404


def test_remote_url_fica_no_json(client, tmp_path):
    remote = _bare_repo(tmp_path)
    r = _create(client, tmp_path, name="gh", remote_url=remote)
    assert r.status_code == 200
    c = r.json()
    stored = json.loads(ConfigManager.CONNECTIONS_FILE.read_text(encoding="utf-8"))
    (saved,) = [x for x in stored["connections"] if x["id"] == c["id"]]
    assert saved["remote_url"] == remote
    assert client.get(f"/api/connections/{c['id']}").json()["remote_url"] == remote


def test_patch_name_and_enabled(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.patch(f"/api/connections/{cid}", json={"name": "renomeada", "enabled": False})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["enabled"]) == ("renomeada", False)


def test_patch_remote_url_and_review_mode(client, tmp_path):
    remote = _bare_repo(tmp_path)
    cid = _create(client, tmp_path).json()["id"]
    r = client.patch(f"/api/connections/{cid}", json={"remote_url": remote, "review_mode": "pr"})
    assert r.status_code == 200
    assert r.json()["remote_url"] == remote and r.json()["review_mode"] == "pr"
    r = client.patch(f"/api/connections/{cid}", json={"remote_url": None})
    assert r.status_code == 200 and r.json()["remote_url"] is None


def test_patch_fields_and_validation(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.patch(f"/api/connections/{cid}", json={"name": "renomeada"})
    assert r.status_code == 200 and r.json()["name"] == "renomeada"
    assert client.patch(f"/api/connections/{cid}",
                        json={"review_mode": "sync"}).status_code == 422
    assert client.patch("/api/connections/nope",
                        json={"name": "a"}).status_code == 404


def test_a_padrao_nao_pode_ser_desativada(client, tmp_path):
    assert client.patch("/api/connections/teste", json={"enabled": False}).status_code == 422
    assert client.patch("/api/connections/teste", json={"name": "x"}).status_code == 200


def test_test_endpoint_ok_and_last_test(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.post(f"/api/connections/{cid}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and isinstance(body["latency_ms"], int) and body["message"]
    last = client.get(f"/api/connections/{cid}").json()["last_test"]
    assert last["status"] == "ok" and last["latency_ms"] == body["latency_ms"]
    assert last["tested_at"]


def test_test_missing_is_404(client, tmp_path):
    assert client.post("/api/connections/nope/test").status_code == 404


def test_delete_204_then_404(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    assert client.delete(f"/api/connections/{cid}").status_code == 204
    assert client.get(f"/api/connections/{cid}").status_code == 404
    assert client.delete(f"/api/connections/{cid}").status_code == 404


def test_set_default_e_delete_da_default_passa_o_posto(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    r = client.put(f"/api/connections/{cid}/default")
    assert r.status_code == 200 and r.json()["is_default"] is True
    assert ConfigManager.load().default == cid
    rows = {c["id"]: c for c in client.get("/api/connections").json()}
    assert rows["teste"]["is_default"] is False and rows[cid]["is_default"] is True
    # apagar a padrão é permitido: o posto passa para outra habilitada
    assert client.delete(f"/api/connections/{cid}").status_code == 204
    assert ConfigManager.load().default == "teste"
    # e apagar a última deixa sem padrão (as rotas de dados passam a dizer como criar)
    assert client.delete("/api/connections/teste").status_code == 204
    assert ConfigManager.load().default is None
    assert client.get("/api/workspaces").status_code == 422


def test_set_default_disabled_is_422_and_missing_is_404(client, tmp_path):
    cid = _create(client, tmp_path, enabled=False).json()["id"]
    assert client.put(f"/api/connections/{cid}/default").status_code == 422
    assert client.put("/api/connections/nope/default").status_code == 404


def test_rota_de_sincronizar_schema_saiu(client, tmp_path):
    cid = _create(client, tmp_path).json()["id"]
    assert client.post(f"/api/connections/{cid}/schema-sync").status_code in (404, 405)


def test_health_mostra_caminho_e_arquivos_quebrados(client, tmp_path, mk):
    mk.tree()  # a primeira escrita transforma a pasta em repositório git
    r = client.get("/api/connections/health")
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert set(row) == {"id", "name", "path", "ok", "parse_errors"}
    assert row["id"] == "teste" and row["ok"] is True and row["parse_errors"] == []
    folder = tmp_path / "dados"
    assert row["path"] == str(folder)
    (folder / "ws" / "dom" / "quebrado.md").write_text("---\n: [\n---\n", encoding="utf-8")
    (row,) = client.get("/api/connections/health").json()
    assert [e["path"] for e in row["parse_errors"]] == ["ws/dom/quebrado.md"]
    assert row["parse_errors"][0]["error"]


def test_health_marca_pasta_sem_git(client, tmp_path):
    c = _create(client, tmp_path).json()
    shutil.rmtree(c["path"], ignore_errors=True)
    rows = {x["id"]: x for x in client.get("/api/connections/health").json()}
    assert rows[c["id"]]["ok"] is False and rows[c["id"]]["path"] == c["path"]
