# plumb-brain: Knowledge OS como segundo cérebro obrigatório do Plumb
Status: construindo T2 · Trilha: profunda · Branch: feature/plumb-brain

## Objetivo
Tornar o Knowledge OS a memória central do Plumb com custo baixo de contexto:
pacote de contexto por projeto em uma chamada (ou injetado por hook), escrita
idempotente em lote, busca que acerta em PT-BR e superfície de ferramentas
enxuta para agentes. Corrigir o que está quebrado no servidor (dependências sem
versão, testes, documentação desatualizada).

## Fora de escopo
- Base compartilhada em equipe (Postgres segue suportado, mas o alvo é SQLite local).
- Embeddings ou busca semântica.
- Mudanças na UI web além do necessário para os campos novos aparecerem.

## Critérios de aceite
- AC1: Dado o fastmcp 4 instalado, quando a suíte roda, então passa inteira; `pyproject.toml` fixa `fastmcp>=4,<5` e `mcp>=2,<3`.
- AC2: Dado `KNOWLEDGE_OS_TOOLSET=agent`, quando o cliente lista ferramentas, então recebe no máximo 10 e instruções com menos de 3.000 caracteres.
- AC3: Dado um item "Migrações com Flyway", quando busco "migração", então ele vem em 1º (sem acento, plural e prefixo resolvidos) e relevância vence `importance`.
- AC4: Dado um repositório ligado a workspace/domain, quando chamo `context_get(project=<caminho>)` ou `knowledge-mcp context --project <caminho>`, então recebo regras, contexto, decisões e procedimentos ativos em Markdown dentro do orçamento de tokens, sem itens substituídos nem ephemeral vencidos; regras com `scope_paths` só aparecem para caminhos que casam.
- AC5: Dado `item_batch_upsert` com chaves novas e existentes, então cria as novas, atualiza as existentes numa transação e devolve `created`/`updated` por chave; sem chave, o create devolve `similar` quando há título parecido.
- AC6: Dado conteúdo com padrão de segredo (chave AWS, chave privada, token do GitHub, `password=...`), quando crio ou atualizo, então recebo erro de validação sem eco do valor.
- AC7: Dado `--hook claude` ou `--hook cursor` com o JSON do hook no stdin, então a saída segue o formato de contexto adicional da ferramenta e nunca quebra a sessão (erro vira mensagem curta).
- AC8: Dado um banco da versão anterior, quando o servidor sobe, então `schema_sync` adiciona as colunas novas e recria o índice FTS com o tokenizer novo, sem perder itens.
- AC9: `health_check` e `knowledge-mcp --version` informam versão do servidor e do schema.

## Design
Opções para o contexto por sessão: A — o agente chama `context_get` · B — hook de
início de sessão injeta `knowledge-mcp context` → escolhida: B com A como
fallback, porque é determinística, tem orçamento e não depende do modelo lembrar.
Opções para chave estável: A — `key` livre única por domain · B — hash do título
→ escolhida: A (o curador controla a chave, upsert previsível).
Contratos / dados / migração: colunas novas em `items` (`key`, `keywords`,
`source`, `status`, `scope_paths`, `expires_at`), tabela `project_links`, FTS
recriado com `unicode61 remove_diacritics 2` e coluna `keywords`; tudo aditivo
via `schema_sync` + marcador de versão do FTS em `schema_meta`.
Riscos e rollback: FTS recriado com `rebuild` (sem perda); rollback = checkout da
master e `schema_sync` (colunas extras são ignoradas pelo código antigo).

## Tasks
- [x] T1 Dependências fixadas, testes compatíveis com fastmcp 4, ruff em `[tool.ruff.lint]` — prova: AC1 — verificar: `pytest -q`
- [ ] T2 Modelo: colunas novas, `project_links`, migração do FTS — prova: AC8 — verificar: `pytest tests/test_schema_sync.py tests/test_fts.py`
- [ ] T3 Busca: BM25 primeiro, PT-BR (diacríticos, plural, prefixo), sem workspace obrigatório, filtra inativos e vencidos — prova: AC3 — verificar: `pytest tests/test_fts.py tests/test_brain_search.py`
- [ ] T4 Upsert, lote, similares, tags/labels editáveis, segredo bloqueado — prova: AC5, AC6 — verificar: `pytest tests/test_brain_write.py`
- [ ] T5 Projetos e pacote de contexto (`project_link`, `context_get`, escopo por caminho, orçamento) — prova: AC4 — verificar: `pytest tests/test_brain_context.py`
- [ ] T6 Perfil `agent` e instruções curtas; versão no health — prova: AC2, AC9 — verificar: `pytest tests/test_toolsets.py`
- [ ] T7 CLI: `context` (com `--hook`), `recent`, `import-pending`, `--version` — prova: AC4, AC7 — verificar: `pytest tests/test_cli_brain.py`
- [ ] T8 Documentação atual (README, MCP_USAGE), STATUS obsoleto removido, notas antigas do Plumb arquivadas — verificar: leitura

## Decisões
- 2026-10-04 usuário: segundo cérebro obrigatório no Plumb; base local (SQLite); com a base fora do ar o fluxo segue com aviso; em arquivo ficam só Workflow/comandos no AGENTS.md, `.plumb/changes` e permissões; base = master; "implemente tudo" aprova este plano (gate 1).
- 2026-10-04 orquestrador (delegado pelo usuário): rules com escopo e skills de projeto migram para itens com `scope_paths`; o curador grava `working` sem perguntar e pede o "sim" para `longterm`/`canonical`.
- 2026-10-04 orquestrador: adotar fastmcp 4 e fixar a faixa, em vez de voltar para a 2.x (conflito de dependências com o pacote `mcp`).

## Notas
- T1: suíte 454 ok / 3 skip. `test_wheel` só passa com TMP fora do AppData quando roda dentro do Claude Desktop (sandbox), fora disso passa normal.
- mypy: 150 erros antigos (disallow_untyped_defs em código legado) — fora do escopo, não piorar.
- Baseline na master `7a3af91`: 16 falhas em 457 testes, 11 por API do fastmcp 4 nos testes, 1 de ambiente (`uv build` na pasta temporária do app), o resto a confirmar.
- `.claude/worktrees/` tem 5 worktrees órfãs de agentes (não registradas no git) — limpar com o usuário.
- O repositório não tem remoto: a distribuição pelo instalador do Plumb depende disso.

## Retro
- correção: o servidor levava ~138 s para subir com uma conexão fora do ar (validate_connection sem connect_timeout + diagnóstico bloqueando o handshake) — corrigido em T1; teste test_default_inacessivel vira regressão
- fato velho: testes dependiam da API do fastmcp 2/3 (`get_tools`, `isError`) e quebraram com a 4 por falta de faixa de versão
