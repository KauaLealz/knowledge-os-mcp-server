"""Testes de isolamento entre conexões e das tools com connection_id."""

import uuid

import pytest
from fastmcp import FastMCP
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from src.config import ConfigManager, ConnectionConfig
from src.db.models import Connection, Workspace
from src.db.session import get_engine
from src.exceptions import NotFoundError, ValidationError
from src.services._common import session_scope
from src.services.connection_service import ConnectionService
from src.services.domain_service import DomainService
from src.services.item_service import ItemService
from src.services.workspace_service import WorkspaceService
from tests.helpers_mcp import run_tool, tools_by_name
from tests.helpers_multidb import catalog, sqlite_url  # noqa: F401


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    """O .knowledge/connections.json (caminho relativo) fica isolado em tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def two(catalog, tmp_path):  # noqa: F811
    svc = ConnectionService()
    a = svc.create("A", "sqlite", sqlite_url(tmp_path / "a.db"))
    b = svc.create("B", "sqlite", sqlite_url(tmp_path / "b.db"))
    return a, b


def test_multiple_connections_isolated(two):
    a, b = two
    WorkspaceService(connection_id=a.id).create("Shared")
    WorkspaceService(connection_id=b.id).create("Shared")  # mesmo nome em outro banco
    WorkspaceService(connection_id=a.id).create("OnlyA")
    assert [w.name for w in WorkspaceService(connection_id=a.id).list()] == ["Shared", "OnlyA"]
    assert [w.name for w in WorkspaceService(connection_id=b.id).list()] == ["Shared"]
    assert WorkspaceService().list() == []
    assert get_engine(a.id) is not get_engine(b.id)
    assert get_engine(a.id) is get_engine(a.id)


def test_engine_de_conexao_inicializa_schema_e_espelha_connection(two):
    a, _ = two
    assert {"workspaces", "items", "items_fts", "connections"} <= set(
        inspect(get_engine(a.id)).get_table_names())
    with session_scope(None, a.id) as s:
        assert s.get(Connection, a.id) is not None


def test_workspace_only_sees_own_connection(catalog):  # noqa: F811
    with session_scope(None) as s:
        s.add_all([Connection(id="c1", name="c1", db_type="sqlite", db_url="sqlite://"),
                   Connection(id="c2", name="c2", db_type="sqlite", db_url="sqlite://")])
        s.commit()
        ws1 = WorkspaceService(s, connection_id="c1")
        ws2 = WorkspaceService(s, connection_id="c2")
        ws1.create("Same")
        ws2.create("Same")
        ws1.create("Extra")
        assert [w.name for w in ws1.list()] == ["Same", "Extra"]
        assert [w.name for w in ws2.list()] == ["Same"]
        with pytest.raises(NotFoundError):
            ws2.get("Extra")
        assert ws2.delete("Extra") is False
        with pytest.raises(ValidationError):
            ws1.create("Same")


def test_unique_constraint_workspace_por_connection(catalog):  # noqa: F811
    with session_scope(None) as s:
        s.add(Connection(id="c1", name="c1", db_type="sqlite", db_url="sqlite://"))
        s.add(Workspace(id=str(uuid.uuid4()), connection_id="c1", name="W"))
        s.commit()
        s.add(Workspace(id=str(uuid.uuid4()), connection_id="c1", name="W"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_conexao_inativa_ou_inexistente_recusada(two):
    a, _ = two
    ConnectionService().update(a.id, is_active=False)
    with pytest.raises(ValidationError):
        get_engine(a.id)
    with pytest.raises(NotFoundError):
        get_engine("nao-existe")


def test_fluxo_completo_e_busca_fts_na_conexao(two):
    a, b = two
    ws = WorkspaceService(connection_id=a.id).create("W")
    dm = DomainService(connection_id=a.id).create(ws.id, "D")
    items = ItemService(connection_id=a.id)
    items.create(workspace_id=ws.id, domain_id=dm.id, type="rule", memory_class="longterm",
                 title="Kubernetes", summary="cluster", content="pods e deployments")
    hits = items.search(ws.id, None, "kubernetes")
    assert [h["title"] for h in hits] == ["Kubernetes"]
    with pytest.raises(NotFoundError):
        ItemService(connection_id=b.id).resolve_workspace_id("W")


def test_delete_connection_descarta_engine(two):
    a, _ = two
    get_engine(a.id)
    ConnectionService().delete(a.id)
    with pytest.raises(NotFoundError):
        get_engine(a.id)


def _add_json_connection(conn_id, path):
    config = ConfigManager.load_or_create()
    config.connections.append(
        ConnectionConfig(id=conn_id, name=conn_id, db_type="sqlite", path=path.as_posix()))
    ConfigManager.save(config)


def test_workspace_create_com_conexao_do_json_sem_reiniciar(catalog, tmp_path):  # noqa: F811
    get_engine()  # servidor "já no ar"
    _add_json_connection("test_conn", tmp_path / "manual.db")  # editada à mão depois
    ws = WorkspaceService(connection_id="test_conn").create("W")
    assert ws.connection_id == "test_conn"
    assert (tmp_path / "manual.db").exists()
    assert WorkspaceService().list() == []


def test_url_alterada_no_json_descarta_engine_em_cache(catalog, tmp_path):  # noqa: F811
    _add_json_connection("c", tmp_path / "um.db")
    first = get_engine("c")
    assert get_engine("c") is first
    config = ConfigManager.load_or_create()
    config.get_connection("c").path = (tmp_path / "dois.db").as_posix()
    ConfigManager.save(config)
    second = get_engine("c")
    assert second is not first and second.url.database.endswith("dois.db")


def test_conexao_desabilitada_ou_removida_do_json_e_recusada(catalog, tmp_path):  # noqa: F811
    _add_json_connection("c", tmp_path / "x.db")
    get_engine("c")
    config = ConfigManager.load_or_create()
    config.get_connection("c").enabled = False
    ConfigManager.save(config)
    with pytest.raises(ValidationError):
        get_engine("c")
    config.connections = [c for c in config.connections if c.id != "c"]
    ConfigManager.save(config)
    with pytest.raises(NotFoundError):
        get_engine("c")


CONNECTION_FREE = {"health_check"}
CONNECTION_REQUIRED = {"schema_sync"}  # alvo explícito: connection_id é obrigatório


def _all_tools():
    import src.main as main

    main.register_all_tools()  # idempotente: sobrescreve tools de mesmo nome
    return tools_by_name(main.mcp)


def test_server_expoe_44_tools():
    tools = _all_tools()
    assert len(tools) == 44
    assert {n for n in tools if n.startswith("connection_")} == {
        f"connection_{a}"
        for a in ("create", "list", "get", "delete", "test", "update")}
    assert "migrate_workspaces" in tools


def test_tools_receive_connection_id():
    tools = _all_tools()
    for name, tool in tools.items():
        if name.startswith("connection_") or name in CONNECTION_FREE | {"migrate_workspaces"}:
            continue
        if name in CONNECTION_REQUIRED:
            assert "connection_id" in tool.parameters["required"], name
            continue
        props = tool.parameters["properties"]
        assert "connection_id" in props, name
        assert "connection_id" not in tool.parameters.get("required", []), name


def test_tools_with_connection_id_roteiam_para_a_conexao(two):
    a, b = two
    m = FastMCP(name="t")
    from src.mcp import workspace_tools

    workspace_tools.register(m)

    def call(name, args):
        return " ".join(b.text for b in run_tool(m, name, args))

    call("workspace_create", {"name": "ToolWs", "connection_id": a.id})
    assert "ToolWs" in call("workspace_list", {"connection_id": a.id})
    assert "ToolWs" not in call("workspace_list", {"connection_id": b.id})
    assert "ToolWs" not in call("workspace_list", {})


def test_default_do_json_roteia_tools_sem_connection_id(two):
    a, b = two
    ConnectionService().set_default(a.id)
    WorkspaceService().create("InA")  # sem connection_id: vale o default do JSON
    assert [w.name for w in WorkspaceService(connection_id=a.id).list()] == ["InA"]
    assert WorkspaceService(connection_id="default").list() == []
    assert WorkspaceService(connection_id=b.id).list() == []
    m = FastMCP(name="t")
    from src.mcp import workspace_tools

    workspace_tools.register(m)
    blocks = run_tool(m, "workspace_list", {})
    assert "InA" in " ".join(x.text for x in blocks)
    ConnectionService().set_default("default")
    assert WorkspaceService().list() == []


def test_item_service_com_engine_da_conexao_resolve_workspace(two):
    a, b = two
    ws = WorkspaceService(connection_id=b.id).create("W")
    assert ItemService(get_engine(b.id)).resolve_workspace_id("W") == ws.id
    ConnectionService().set_default(a.id)
    assert ItemService(get_engine(b.id)).resolve_workspace_id("W") == ws.id
    with pytest.raises(NotFoundError):
        ItemService(get_engine()).resolve_workspace_id("W")
