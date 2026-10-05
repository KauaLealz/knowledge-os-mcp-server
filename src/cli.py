"""Atalho para instalações editáveis antigas (entry point `src.cli:main`).

Não faz parte do wheel (o pacote é `knowledge_os`). Vale só até o usuário reinstalar.
"""

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print(
        "knowledge-mcp: instalacao antiga: reinstale com "
        f"`uv tool install --editable {Path(__file__).resolve().parent.parent} --force`",
        file=sys.stderr,
    )
    from knowledge_os.cli import main as real_main

    return real_main(argv)


if __name__ == "__main__":
    sys.exit(main())
