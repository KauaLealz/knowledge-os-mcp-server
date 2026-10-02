# front-v2: front estilo documentação + gestão de conexões
Status: construindo T3 (trilha B, em paralelo) · Trilha: profunda · Branch: feature/front-v2 · Depende de: mcp-stdio-home

## Objetivo
Substituir o `src/api/static/index.html` por um front no nível de um produto de documentação/knowledge-as-a-service: sidebar em árvore, página de item com TOC, Ctrl/Cmd+K, edição inline e gestão de conexões (com senha). Tudo sobre a mesma fonte do MCP (connections.json) e sem build step. Por fim, refazer o workspace `projpro` pelas tools MCP.

## Fora de escopo
- Retrocompatibilidade (sem campo `db_url` na API, sem alias).
- Grafo visual, upload de artifacts (só listar e baixar), import/export e migrate_workspaces pela UI, histórico de versões.
- Runner JS, npm, Vite, React.

## Critérios de aceite
API
- AC1: `GET /api/connections` lista o catálogo `default` e as conexões do JSON com id, name, db_type, path|host/port/database/username, password_set (bool), enabled, is_default e last_test. Com uma conexão cuja senha é `supersecret`, esse valor não aparece em nenhuma resposta da API.
- AC2: `POST /api/connections` aceita campos estruturados e `password` (só escrita), com `extra="forbid"`. Uma URL com senha embutida, ou o campo antigo `db_url`/`password_env`, devolve 422. A senha vai para o connections.json e nunca volta.
- AC3: `POST /{id}/test` devolve {status, message, latency_ms}, com a mensagem redigida (sem a senha). `PATCH /{id}` altera os campos; senha ausente no corpo mantém a atual, um valor novo substitui e `null` limpa. `DELETE /{id}` devolve 204. Excluir o default, ou editar/excluir o catálogo, devolve 422; id inexistente devolve 404.
- AC4: `PUT /{id}/default` grava o default (com a conexão desabilitada: 422). `POST /{id}/schema-sync?dry_run=true` só lista; com `dry_run=false`, aplica.
- AC5: Um workspace criado com `X-Connection-Id: A` não aparece com `B`. Sem o header, vale o default do JSON; id inexistente dá 404 e conexão desabilitada dá 422.
- AC6: Com default = A no JSON, uma tool MCP chamada sem connection_id opera em A.
- AC7: `GET /api/workspaces/{id}/tree` devolve, numa chamada só, os domains com item_count e os items (id, title, type, memory_class, confidence, updated_at).

UI (roteiros no navegador embutido, em Design › Provas)
- AC8 (R1): O token sai da barra de endereço. A sidebar tem o switcher Connection → Workspace e a árvore Domain (com contagem) → Item (ícone por type). As páginas de Workspace e de Domain mostram cards. O tema system/light/dark persiste ao recarregar.
- AC9 (R2): Página de item com breadcrumb, chips (type, memory_class, barra de confidence, importance, tags, labels, "atualizado há X"), banner quando confidence < 60 ou quando um ephemeral está a ≤ 2 dias do TTL, Markdown sanitizado (`<img onerror>` não entra no DOM), código com highlight, TOC de H2/H3, relações saindo e chegando, artifacts, prev/next, "Copiar como Markdown" e "Ver Markdown".
- AC10 (R3): Ctrl/Cmd+K abre a paleta com os grupos Recentes / Items / Domains-Workspaces / Ações / Configurações. Enter navega, `?` abre os atalhos, Esc fecha.
- AC11 (R4): `e` alterna entre Ler e Editar no mesmo lugar (textarea mono + preview). Ctrl/Cmd+S salva, e a alteração persiste ao recarregar. Os modais Novo item, Novo workspace e Novo domain funcionam.
- AC12 (R5): A tela Conexões tem a lista (ponto de status, último teste, selo Default) e o detalhe com formulário (inclui senha), Testar, "Salvar e testar" (mensagem + latência), Definir como default, Sincronizar schema (dry-run e depois aplicar) e a Zona de perigo com confirmação digitada. Trocar a conexão recarrega os workspaces.
- AC13: A senha só trafega no corpo de POST/PATCH, e só quando preenchida. O campo é `type=password`, vem vazio ao editar (com "definida" quando password_set) e é limpo depois de salvar. A senha não vai em URL, localStorage, sessionStorage nem aparece no DOM, em toast ou em log do console.
- AC14 (R6): Em 375px a sidebar vira drawer e não há scroll horizontal. Abaixo de 1000px a TOC some. Depois de reiniciar o servidor, aparece a tela "Sessão expirada".
- AC15: O `projpro` é refeito pelas tools MCP a partir de C:\Polara\projpro\AGENTS.md e .claude/rules/*.md: um domain por área, items fiéis à fonte citando o arquivo de origem, label `reference` e relações entre eles.

## Design
**Seleção de conexão.** Header `X-Connection-Id`, aplicado em um único ponto (api.js). `deps.get_connection_id()` lê o header ou cai no default do JSON.
**API de conexões.** O ConnectionService continua como fonte única sobre o JSON e ganha update, set_default, last_test em memória e schema-sync (inclusive para o catálogo). Senha só de escrita. `db_url` e `password_env` saem do contrato. A tabela `connections` fica só como espelho da FK.
**Front.** Alpine 3 + ES modules + CSS próprio com tokens + router por hash. O Tailwind Play CDN foi descartado: faz JIT em runtime, causa FOUC e não é recomendado para produção. Estrutura de arquivos em src/api/static/:
- index.html: shell, com o tema aplicado antes do paint e um import map com versões fixas (jsdelivr +esm).
- css/tokens.css e css/app.css: system-ui/Inter 15–16px, line-height 1.65, um acento, cinzas neutros, raio 6px, grid sidebar 272px / conteúdo 720px / TOC, modo `wide`.
- js/main.js, api.js, router.js, store.js, markdown.js (marked → DOMPurify → hljs) e shortcuts.js.
- js/views/{sidebar,workspace,domain,item,editor,palette,connections}.js.

As rotas usam `#/c/:conn/w/:ws/d/:dm/i/:item[/edit]` e `#/settings/connections[/:id|/new]`. A conexão vai na rota, então recarregar mantém o contexto.
**Provas de UI.**
- R0: home temporário, `knowledge-mcp ui --no-browser` em background, dados de semente criados por `curl` com o token, e abrir a URL impressa.
- R1–R6: os roteiros dos ACs 8–14, verificados no navegador embutido com `read_page`/`javascript_tool` (asserções como `document.querySelector('[onerror]')===null` e `scrollWidth<=innerWidth`).

**projpro.** Popular `projpro-v2` pelas tools MCP, conferir contra as fontes, fazer `workspace_export` do `projpro` raso como backup, excluir o raso e renomear o v2 via `PUT /api/workspaces/{id}` (o MCP não tem rename). O raso foi criado nesta sessão com conteúdo mínimo.
**Riscos e rollback.**
- O front depende de CDN e não funciona offline.
- `set-default` muda o roteamento do MCP: se o default apontar para um banco fora do ar, as tools chamadas sem id falham com erro explícito.
- A senha fica em texto no JSON e a UI a manda por HTTP em localhost (decisão do usuário; risco aceito).
- A T2 mexe em todas as rotas de dados: a suíte da API cobre.
- Rollback: reverter os commits do front.

## Tasks
- [ ] T1 API de conexões sobre o JSON, com senha só de escrita. Arquivos: src/api/routes/connection.py, src/api/schemas/{requests,responses}.py, src/services/connection_service.py, tests/api/test_connections.py. Prova: AC1–AC4. Verificar: `python -m pytest tests/api/test_connections.py -q`.
- [ ] T2 `X-Connection-Id` + default real (deps, todas as rotas de dados, workspace.py:60, session e services). Arquivos: src/api/deps.py, src/api/routes/*.py, src/db/session.py, src/services/{_common,workspace_service,item_service,migration_service}.py, tests/api/test_connection_routing.py, tests/test_multidb.py. Prova: AC5, AC6. Verificar: `python -m pytest tests/api/test_connection_routing.py tests/test_multidb.py -q`.
- [x] T3 `GET /api/workspaces/{id}/tree`. Arquivos: src/api/routes/workspace.py, src/api/schemas/responses.py, tests/api/test_workspaces.py. Prova: AC7. Verificar: `python -m pytest tests/api/test_workspaces.py -q`.
- [ ] T4 Shell, tokens, tema, router, api.js, store, sidebar e páginas de Workspace e Domain. Inclui tests/api/test_static.py. Prova: AC8. Verificar: `python -m pytest tests/api/test_static.py -q` + R1.
- [ ] T5 Página de item em modo leitura. Arquivos: js/views/item.js, js/markdown.js, index.html, css/app.css. Prova: AC9. Verificar: test_static + R2.
- [ ] T6 Paleta Ctrl/Cmd+K + atalhos. Arquivos: js/views/palette.js, js/shortcuts.js, index.html, css/app.css. Prova: AC10. Verificar: test_static + R3.
- [ ] T7 Edição inline + modais Novo item, Novo workspace e Novo domain. Arquivos: js/views/editor.js, js/views/item.js, index.html, css/app.css. Prova: AC11. Verificar: test_static + R4.
- [ ] T8 Configurações → Conexões (com campo de senha) + asserções no test_static de que a senha não é lida de volta nem guardada em storage. Arquivos: js/views/connections.js, index.html, css/app.css, tests/api/test_static.py. Prova: AC12, AC13. Verificar: test_static + R5.
- [ ] T9 Responsivo, estados vazio/erro/sessão expirada, README e STATUS. Prova: AC14. Verificar: test_static + R6.
- [ ] T10 Refazer o projpro pelas tools MCP registradas (fluxo na seção projpro). Sem commit. Prova: AC15. Verificar: workspace_list, domain_list e item_search com "Flyway", "filtro Hibernate" e "BFF".

## Decisões
- 2026-10-02 usuário: front sem build step (rejeitou React+Vite por peso), com libs via CDN e servido pelo FastAPI.
- 2026-10-02 usuário: front "totalmente refatorado", com navegação no estilo de ferramentas de knowledge-as-a-service e páginas de documentação, e gestão de conexões.
- 2026-10-02 usuário: senha da conexão no JSON de config; sem retrocompatibilidade.
- 2026-10-02 usuário delegou as perguntas; decidi: "Definir como default" também roteia o MCP; UI só em 127.0.0.1; o `projpro` raso é exportado, excluído e substituído pelo v2 sem novo gate.

## Notas
- Referências pesquisadas: Mintlify, GitBook, Docusaurus/Infima, Nextra, Outline, Notion, Guru, Slab, Obsidian, Linear e Grafana.
- A busca da paleta usa `summary` como trecho, porque o `snippet()` do FTS só existe no SQLite.
- A tool MCP `connection_create` não recebe senha (para ela não passar pela conversa): a senha entra pela UI.

## Retro
