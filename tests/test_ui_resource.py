"""A UI local exposta como resource do MCP (knowledge-os://ui), não só stderr."""

import asyncio
import json

import knowledge_os.main as main_mod


def _read_ui_resource() -> dict[str, object]:
    async def go():
        return await main_mod.mcp.read_resource("knowledge-os://ui")

    result = asyncio.run(go())
    return json.loads(result.contents[0].content)


def test_ui_resource_esta_listado():
    async def go():
        return await main_mod.mcp.list_resources()

    resources = asyncio.run(go())
    assert str(resources[0].uri) == "knowledge-os://ui"
    assert any(str(r.uri) == "knowledge-os://ui" for r in resources)


def test_ui_resource_sem_background_ui_aponta_porta_padrao_e_serving_false(monkeypatch):
    monkeypatch.setattr(main_mod, "_background_ui", None)
    data = _read_ui_resource()
    assert data == {"url": f"http://127.0.0.1:{main_mod.UI_DEFAULT_PORT}/ui/", "serving": False}


def test_ui_resource_reflete_porta_e_status_da_background_ui(monkeypatch):
    ui = main_mod.BackgroundUI(port=9999)
    ui.serving = True
    monkeypatch.setattr(main_mod, "_background_ui", ui)
    data = _read_ui_resource()
    assert data == {"url": "http://127.0.0.1:9999/ui/", "serving": True}
