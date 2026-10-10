"""As ferramentas MCP devolvem os dicionários dos serviços: não dependem dos schemas pydantic
da API (que são da camada HTTP e mudam com ela)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_tools_nao_carrega_os_schemas_da_api(tmp_path):
    code = ("import sys; import knowledge_os.mcp.tools; "
            "print(sorted(m for m in sys.modules if m.startswith('knowledge_os.schemas')))")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), KNOWLEDGE_OS_HOME=str(tmp_path))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, env=env, cwd=tmp_path)
    assert out.stdout.strip() == "[]"
