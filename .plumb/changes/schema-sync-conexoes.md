# schema-sync-conexoes: registro único de conexões, sincronização de schema e tipo `task`
Status: construindo T0 · Trilha: padrão · Branch: feature/schema-sync-conexoes

## Objetivo
Hoje existem dois cadastros de conexão que não se enxergam:
- `connection_create`, `connection_list`, `connection_get`, `connection_delete`, `connection_test` e as tools com `connection_id` usam a tabela `connections` do catálogo. Ela é resolvida em `ConnectionManager._open`, em `src/db/session.py:143`.
- `connection_init_db`, `migrate_workspaces` e o startup usam o `.knowledge/connections.json`.

Por isso, uma conexão criada por tool não pode ser inicializada, e uma conexão do JSON não pode ser usada pelas tools de workspace. Além disso, `connection_create` não cria a estrutura do banco. O `init_db` só cria tabelas que faltam e tem uma única migração feita à mão (`_migrate_legacy_workspaces`).

Resultados esperados:
- O JSON passa a ser o único cadastro.
- Criar uma conexão já deixa o banco pronto.
- Uma tool cria o schema que falta ou atualiza um schema defasado.
- Um tipo de item neutro, `task`, fica disponível para memória de trabalho.
- As instruções do MCP chegam de fato ao agente e explicam como configurar as conexões.

## Fora de escopo
- Status, fluxo ou tools próprias para `task`: é um tipo como os outros, e quem define a regra é o workflow do agente.
- Expiração automática de itens `ephemeral` (o `ttl_days` continua só informativo).
- Mudanças destrutivas de schema: remover coluna, trocar tipo ou recriar constraint. Elas são reportadas, não aplicadas.
- Criptografia de senha no JSON.
- Alembic ou migrações versionadas por arquivo.

## Critérios de aceite
- AC1: Dado `item_create(type="task", ...)`, então o item é criado. Um tipo fora da lista continua sendo rejeitado.
- AC2: Dado um SQLite que não existe, quando `schema_sync` roda, então arquivo, tabelas, índices e FTS são criados. O retorno é `status="created"`.
- AC3: Dado um banco sem uma coluna ou um índice do modelo atual, quando `schema_sync` roda, então a coluna ou o índice é adicionado. O retorno é `status="updated"` e lista o que foi aplicado.
- AC4: Dado um banco já igual ao modelo, quando `schema_sync` roda, então nada muda e o retorno é `status="up_to_date"`.
- AC5: Dado um banco com uma diferença não aditiva (por exemplo, o tipo de uma coluna mudou), quando `schema_sync` roda, então ele não altera essa diferença. O retorno é `status="drift"` com a lista em `pending_manual`.
- AC6: Dado `schema_sync(..., dry_run=True)`, então nada é gravado no banco e o retorno lista o que seria aplicado.
- AC7: Dado `connection_create(...)` com um banco acessível, então a conexão é gravada no `.knowledge/connections.json` e o schema é sincronizado na mesma chamada.
- AC8: Dada uma conexão adicionada à mão no JSON, quando `workspace_create(..., connection_id=<id>)` roda, então o workspace é criado naquele banco, sem reiniciar o servidor.
- AC9: Dadas conexões que existem só na tabela `connections` de um catálogo antigo, quando o servidor sobe, então elas são importadas para o JSON uma única vez.
- AC10: Dado o servidor iniciado, então o `instructions` do FastMCP contém o `INSTRUCTIONS.md`, incluindo a seção de configuração de conexões (formato do JSON, campos por `db_type`, `password_env`, `enabled`, `default`).

## Tasks
- [x] T0 Commitar o trabalho pendente de T6 a T10 em commits próprios na branch nova, para a base do diff ficar limpa. Arquivos: os modificados no `git status`. Verificar: `pytest -q` (289 passed).
  - T6 docs + T7 multi-db + T8a API + T9 config + T10 instructions (5 commits)
  - Base limpa: schema-sync-conexoes começa depois
- [ ] T1 Adicionar o tipo `task` à lista de tipos aceitos. Arquivos: `src/schemas/item_schemas.py`, `tests/test_items.py`. Prova: AC1. Verificar: `pytest tests/test_items.py -q`.
- [ ] T2 Criar o serviço de sincronização de schema em `src/db/schema_sync.py`:
  - compara `Base.metadata` com o `inspect()` do banco;
  - aplica o que é aditivo (tabelas, colunas, índices, FTS do dialect);
  - reporta o que não é aditivo;
  - grava a versão numa tabela `schema_meta`;
  - substitui `_migrate_legacy_workspaces`, e `init_db` passa a chamar o sync.

  Arquivos: `src/db/schema_sync.py`, `src/db/session.py`, `tests/test_schema_sync.py`. Prova: AC2 a AC6. Verificar: `pytest tests/test_schema_sync.py -q`.
- [ ] T3 Tornar o JSON o cadastro único:
  - `ConnectionManager._open` resolve pelo `ConfigManager`, relendo o arquivo a cada resolução e descartando o engine em cache se a URL mudou;
  - `ConnectionService` lê e grava o JSON e sincroniza o schema no `create`;
  - a tabela `connections` fica só como espelho da FK em cada banco;
  - o startup importa linhas antigas do catálogo para o JSON.

  Arquivos: `src/config.py`, `src/db/session.py`, `src/services/connection_service.py`, `tests/test_connections.py`, `tests/test_multidb.py`. Prova: AC7 a AC9. Verificar: `pytest tests/test_connections.py tests/test_multidb.py -q`.
- [ ] T4 Criar a tool `schema_sync(connection_id, dry_run=False)` no lugar de `connection_init_db`. `migrate_workspaces` sincroniza o destino antes de copiar, e o startup sincroniza as conexões ativas. O total de tools continua 40. Arquivos: `src/mcp/connection_tools.py`, `src/main.py`, `tests/test_connection_tools.py`, `tests/test_artifacts.py`. Prova: AC2 a AC6 via tool. Verificar: `pytest tests/test_connection_tools.py -q`.
- [ ] T5 Ligar o `INSTRUCTIONS.md` ao `FastMCP(instructions=...)`. Adicionar a seção "Configurar conexões" (formato do JSON, exemplo por banco, `password_env`, `enabled` e `default`, editar o JSON sem reiniciar) e mencionar `task` e `schema_sync`, sem repetir o que os docstrings já dizem. Atualizar o `docs/MCP_USAGE.md`. Arquivos: `src/main.py`, `src/mcp/INSTRUCTIONS.md`, `docs/MCP_USAGE.md`, `tests/test_main.py`. Prova: AC10. Verificar: `pytest tests/test_main.py -q`.

## Decisões
- 2026-10-02 User: password_env obrigatório, sem senha embutida na URL
- 2026-10-02 User: diferenças destrutivas só reportadas, sem Alembic
- 2026-10-02 User: remover `connection_init_db`, não manter alias
- 2026-10-02 User: rodar T1-T5 em paralelo (5 worktrees)

## Notas
- Os testes da T7 que mexem na tabela `connections` vão mudar na T3. Isso é esperado, não regressão.
- O comentário `# +6 tools` em `register_all_tools` está desatualizado (T10). Corrigir na T4.
- T0: 5 commits (T6, T7, T8a, T9, T10) antes de qualquer mudança de schema-sync-conexoes.
