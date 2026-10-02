# mcp-stdio-home: Knowledge OS instalável via stdio, com home de dados único
Status: construindo T0 · Trilha: profunda · Branch: feature/mcp-stdio-home

## Objetivo
Registrar o MCP Knowledge OS no Claude Code (stdio, escopo user, igual ao `secrets`) funcionando a partir de qualquer cwd. Os dados passam a viver em um home único (`~/.knowledge-os`), não no projeto aberto nem em site-packages. A senha da conexão fica no connections.json. A UI sobe por `knowledge-mcp ui`, com token real por start.

## Fora de escopo
- Front novo, API de conexões e seleção de conexão: mudança `front-v2`.
- Retrocompatibilidade: sem migração de dados do repo, sem normalização de JSON legado, sem alias de campo.
- Renomear o pacote `src`, publicar no PyPI, CI.
- Transporte MCP HTTP/SSE; acesso à UI pela rede.
- Criptografar a senha em repouso.

## Critérios de aceite
- AC1: Com `KNOWLEDGE_OS_HOME=<dir>`, connections.json, knowledge.db, artifacts/, exports/ e backups/ ficam em `<dir>`. Sem a variável, o home é `~/.knowledge-os`. Importar `src.config` não cria diretório.
- AC2: Conexão sqlite com `path` relativo resolve contra o home, em qualquer cwd. Path absoluto não muda. O id `default` é reservado.
- AC3: Na primeira execução o connections.json nasce com `default: "default"` (o catálogo `<home>/knowledge.db`, que continua sendo o banco padrão e aceita `MCP_DB_PATH` como override) e `connections: []`. O `sqlite_local` deixa de existir. O INSTRUCTIONS.md descreve o home e o catálogo.
- AC4: A suíte completa passa sem falhas e não altera arquivo do repo nem o `~/.knowledge-os` real.
- AC5: Com cwd e home temporários, o servidor sobe por subprocess e um cliente MCP stdio faz initialize → list_tools → health_check. Resultado esperado: 40 tools, health_check ok, nada criado no cwd, stdout só com protocolo.
- AC6: `knowledge-mcp ui --port P` escuta em 127.0.0.1 e imprime `http://127.0.0.1:P/ui/#token=<t>`, com t ≥ 32 caracteres e novo a cada start. `/api/*` responde 401 sem token ou com token errado e 200 com o certo; sem token configurado, recusa tudo.
- AC7: Requisição com `Origin: http://evil.test` não recebe ACAO. Com `Host: evil.test`, a resposta é 400.
- AC8: O wheel inclui `src/mcp/INSTRUCTIONS.md` e `src/api/static/**`.
- AC9: Depois de `uv tool install --editable`, `knowledge-mcp --check-db` rodado em `C:\` responde `database: connected` e não cria nada em `C:\`.
- AC10: `claude mcp list` mostra `knowledge-os ✔ Connected`. Numa sessão nova em outro projeto, health_check responde ok.
- AC11: A conexão tem o campo `password` no connections.json (substitui `password_env`), usado por `get_url()`. A senha não aparece em `repr`, em logs, em mensagens de erro, nem no retorno de nenhuma tool MCP (`connection_get/list` devolvem `password_set: bool`). `connection_create`/`connection_update` não têm parâmetro de senha, para ela não passar pela conversa: ela entra pela UI ou editando o JSON. O arquivo é gravado com chmod 600 quando o SO permite.

## Design
**Dados.** `KNOWLEDGE_OS_HOME` (default `~/.knowledge-os`). Alternativas descartadas: platformdirs (dependência nova) e PROJECT_ROOT (quebra com wheel). As constantes são lidas no import, e o `mkdir` só roda em `ensure_home()` (no main e no ui). O path sqlite relativo resolve contra `config.KNOWLEDGE_HOME` no momento da chamada. `save()` é atômico (tmp + os.replace). Os testes usam um home temporário por sessão e por teste.
**Catálogo × sqlite_local.** O catálogo `default` continua virtual (`<home>/knowledge.db`); `ConnectionsFile.default` aceita `"default"`. Sem retrocompatibilidade, o `sqlite_local` e o `import_legacy_connections` (compat da tabela `connections`) são removidos, junto com os testes deles.
**Dados antigos.** O `database/` do repo fica intocado e não é migrado: tem só o `projpro` raso, que será refeito pelo MCP (mudança `front-v2`).
**Senha.** Decisão do usuário: fica em texto no connections.json, que vive em `~/.knowledge-os` (fora do repo). `ConnectionConfig.password` com `repr=False`, e a redação de erros passa a mascarar o valor. `password_env` sai. A API e a UI nunca devolvem a senha, só `password_set`.
**Instalação.** `uv tool install --editable <repo>` + `claude mcp add --scope user knowledge-os -e KNOWLEDGE_OS_HOME=... -e LOG_LEVEL=WARNING -- knowledge-mcp`. Mudanças de código passam a valer ao reiniciar a sessão. O package-data entra para manter `uvx --from` possível.
**UI e auth.** Subcomando `ui [--port] [--no-browser]` (somente 127.0.0.1); sem subcomando, roda o stdio de hoje. O token vem de `secrets.token_urlsafe(32)` a cada start e vai no fragmento `#token=`. A comparação usa `hmac.compare_digest`, com fail closed. O CORS sai (mesma origem) e entra `TrustedHostMiddleware(127.0.0.1, localhost)`. O `__main__` com `0.0.0.0` é removido.
**Riscos e rollback.** Senha em texto: qualquer processo do usuário lê o JSON (decisão assumida); não colocar `~/.knowledge-os` em pasta sincronizada. Vários processos no mesmo SQLite: WAL + busy_timeout já configurados. Handshake lento se uma conexão remota estiver fora do ar (report_connections testa todas): fica em Notas. Rollback: `claude mcp remove --scope user knowledge-os` + `uv tool uninstall knowledge-mcp`.

## Tasks
- [x] T0 Deixar a linha de base verde. Fixture autouse isola o CONNECTIONS_FILE; `git restore .knowledge/connections.json`, que vazou a entrada `extra`; ajuste de 3 testes obsoletos (test_password_never_exposed sobre o JSON; 6 connection_* em test_server_expoe_40_tools; schema_sync nas exceções de test_tools_receive_connection_id). Arquivos: tests/conftest.py, tests/api/test_connections.py, tests/test_multidb.py. Prova: AC4 parcial. Verificar: `python -m pytest -q` com 0 failed e `git status --short .knowledge` vazio.
- [x] T1 Home de dados: ensure_home, CONNECTIONS_FILE/DB_PATH no home, sqlite relativo resolvido, `default` reservado e aceito, default config nova, save atômico, remoção do import_legacy_connections e do sqlite_local, INSTRUCTIONS.md, `.knowledge/` no .gitignore + `git rm --cached .knowledge/connections.json`. Arquivos: src/config.py, src/main.py, src/mcp/INSTRUCTIONS.md, .gitignore, tests/conftest.py, tests/test_config.py, tests/test_home.py, tests/test_main.py. Prova: AC1–AC4. Verificar: `python -m pytest tests/test_home.py tests/test_config.py tests/test_main.py tests/test_multidb.py -q`.
- [x] T2 Senha no JSON: `password` substitui `password_env` (get_url, repr, redação, chmod 600 best-effort), `password_set` nos retornos, tools MCP sem parâmetro de senha. Arquivos: src/config.py, src/services/connection_service.py, src/services/_common.py, src/mcp/connection_tools.py, src/db/dialects/*.py (redação), tests/test_config.py, tests/test_connections.py, tests/test_connection_tools.py. Prova: AC11. Verificar: `python -m pytest tests/test_config.py tests/test_connections.py tests/test_connection_tools.py tests/test_dialects.py -q`.
- [x] T3 Subcomando `ui` com token por start, bind em 127.0.0.1 e TrustedHost, sem CORS. Arquivos: src/main.py, src/api/auth.py, src/api/main.py, tests/api/conftest.py, tests/api/test_auth.py, tests/test_cli_ui.py. Prova: AC6, AC7. Verificar: `python -m pytest tests/test_cli_ui.py tests/api/test_auth.py -q`.
- [ ] T4 package-data + teste de handshake stdio real por subprocess + seção "Instalação" no README. Arquivos: pyproject.toml, tests/test_stdio.py, README.md. Prova: AC5, AC8. Verificar: `python -m pytest tests/test_stdio.py -q` + inspeção do wheel gerado por `uv build --wheel`.
- [ ] T5 Instalar e registrar (operação local, sem commit). `uv tool install --editable`, `--check-db` em `C:\`. Depois, **só com aprovação explícita no chat** (altera ~/.claude.json): `claude mcp add --scope user knowledge-os ...`. Prova: AC9, AC10. Verificar: `claude mcp list` + health_check numa sessão nova em C:\Polara\projpro.

## Decisões
- 2026-10-02 usuário: instalar como o MCP `secrets` (stdio, escopo user), com as tools nativas nas sessões do Claude Code.
- 2026-10-02 usuário: a senha da conexão fica no JSON de config (substitui o `password_env` decidido em schema-sync-conexoes); `connection_init_db` continua removida.
- 2026-10-02 usuário: sem preocupação com retrocompatibilidade — sem migração do `database/`, sem normalização de JSON legado.
- 2026-10-02 usuário delegou as perguntas; decidi: "Definir como default" também roteia o MCP; a UI fica só em 127.0.0.1; o `projpro` é refeito (ver front-v2).

## Notas
- Linha de base em 2026-10-02: 308 passed, 7 failed, 3 skipped. As 7 falhas vão para a T0: 4 resolvidas pela isolação do JSON e 3 ajustadas por estarem obsoletas.
- Arquivos vazios que podem ser apagados: `knowledge.db` na raiz e `.knowledge/knowledge.db` (ambos no gitignore).
- `run_knowledge_os.sh` (não versionado) roda o uvicorn em 0.0.0.0; depois da T3 ele só devolve 401. Substituir por `knowledge-mcp ui`.
- Cada task também roda `ruff check src tests`.

## Retro
- correção: o usuário apontou que eu populava o workspace chamando services Python em vez de usar o MCP — turno anterior desta sessão
- fato velho: INSTRUCTIONS.md:31 diz que o default é `sqlite_local`; o default efetivo é o catálogo `default` — src/db/session.py:108-111
- regra: senha da conexão fica no JSON de config (substitui a regra password_env) — decisão do usuário
