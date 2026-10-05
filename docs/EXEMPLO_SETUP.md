# Exemplo de Setup — MCP Knowledge OS

Passo a passo para quem está começando. Depois, siga com
[FLUXO_COMPLETO.md](FLUXO_COMPLETO.md) e consulte a [ARQUITETURA.md](ARQUITETURA.md).
Voltar ao [README](../README.md).

## 1. Instalar

Requer Python 3.12+.

```bash
python -m venv venv
source venv/bin/activate          # Linux/macOS
# .\venv\Scripts\Activate.ps1     # Windows PowerShell

pip install -e ".[dev]"
```

Equivalente: `make dev`.

## 2. Bootstrap do banco

Cria as tabelas, o índice FTS5 e as 5 labels padrão
(`official`, `critical`, `experimental`, `deprecated`, `reference`). É idempotente.

```bash
python src/main.py --bootstrap     # saída final: bootstrap: OK
python src/main.py --check-db      # saída final: database: connected
```

Equivalente: `make bootstrap` e `make check-db`.

## 3. (Opcional) Criptografia

Por padrão o banco é SQLite sem criptografia em `~/.knowledge-os/knowledge.db` (ou `<KNOWLEDGE_OS_HOME>/knowledge.db`).
Para usar SQLCipher (AES-256), defina uma chave de no mínimo 16 caracteres **antes**
do bootstrap:

```bash
cp .env.example .env
export MCP_DB_KEY="$(openssl rand -base64 32)"
```

Guarde a chave: sem ela o banco criptografado não abre. Não é possível trocar o modo
de um banco já criado apenas mudando a variável; crie um novo banco ou exporte e
importe o workspace.

## 4. Iniciar o servidor

```bash
python src/main.py                 # STDIO, padrão MCP (make run)
```

Para registrar em um cliente MCP (exemplo Claude Code):

```bash
claude mcp add knowledge -- python /caminho/para/second-brain-mcp-server/src/main.py
```

## 5. Primeiras chamadas

O cliente MCP enxerga os 32 tools. Uma sequência mínima:

```python
workspace_create(name="Personal", description="Notas pessoais")
domain_create(workspace="Personal", name="Homelab")
item_create(
    workspace="Personal", domain="Homelab", type="procedure", memory_class="longterm",
    title="Reiniciar o proxy", summary="Passos para reiniciar o proxy reverso",
    content="1. docker compose restart proxy\n2. verificar logs",
    tags=["docker"], labels=["official"],
)
item_search(workspace="Personal", query="proxy")   # retorna id, title, summary, score
item_get(item_id="<id retornado>")                  # retorna o content completo
```

## 6. Verificar a instalação

```bash
make test        # pytest -v
make test-cov    # com cobertura (relatório em htmlcov/)
make lint        # ruff check src/ tests/
make typecheck   # mypy src/
```

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `database: connected` não aparece | rode `--bootstrap` primeiro |
| Erro de chave ao abrir o banco | `MCP_DB_KEY` diferente da usada na criação |
| `ModuleNotFoundError: mcp` ao rodar | rode pela raiz: `python src/main.py` (o script já ajusta o `sys.path`) |
