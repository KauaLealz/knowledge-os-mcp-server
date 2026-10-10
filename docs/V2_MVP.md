# Knowledge OS v2 (MVP): contrato de implementação

Este documento é a fonte de verdade da implementação da v2. A spec original e completa está no
cérebro: `C:\Users\kauasantos\knowledge-os-pessoal\pessoal\second-brain-mcp-server\change\brain-v2.md`
(40 resultados esperados, com o "observa-se" de cada um). **Onde este documento e a spec
divergem, vale este.** É um MVP: nada de compatibilidade com a API antiga.

A v2 **evolui o código atual** (`feature/sem-sqlite`, já em `master`): mesma arquitetura (pasta
git por conexão, `FileStore`, `Brain`/`Snapshot`/`Draft`, serviços finos, MCP/API/CLI finos). Não
reescreva o que já funciona; troque o que o modelo novo exige.

## 1. Cortes do MVP

- **Sem compatibilidade nas ferramentas**: `item_save` e as demais só aceitam o v2; campo
  desconhecido é erro que lista os válidos. Sem aliases de tipo/status, sem `level`, sem `relations`
  no `item_save`, sem avisos de campos removidos.
- **Exceção, só na leitura de arquivo** (`item_file.parse_item_file`): os dados reais do usuário
  estão no formato antigo e não podem sumir. O parser traduz, na leitura, o que for antigo
  (seção 3.3); a regravação já sai em v2. Nada além disso.
- **Sem script de migração**, sem `--upgrade`, sem `rename_v2`.
- **Sem drift** (`verified_commit` é gravado pelo feedback, mas o servidor não confere commits).
- **Sem manutenção diária**: item vencido some da busca, nunca é apagado sozinho.
- **Fica**: tudo mais da spec, em especial o modelo, o `scope`, a busca explicada, relações e grafo,
  tags gerenciadas, as 32 ferramentas, o pacote do hook, o feedback com contadores, o relatório e o
  front v2.

## 2. Taxonomia fechada (`knowledge_os/model.py`, fonte única)

| Tipo | Subtipos (todos opcionais) |
|---|---|
| `rule` | `code`, `pattern`, `security`, `business`, `process`, `decision` |
| `howto` | `procedure`, `troubleshoot` |
| `context` | `product`, `map`, `stack`, `glossary`, `environment` |
| `spec` | `change`, `setup`, `dream` |
| `secret` | (nenhum) |

- **Status:** `active`, `review`, `archived`; só `spec` aceita também `draft` e `done`. `expired`
  é derivado (ttl vencido), nunca gravado.
- **scope:** `scoped` | `workspace` | `global`. **origin:** `user` | `code` | `agent` (padrão `agent`).
- **Relações:** `related_to`, `depends_on`, `implements`, `references`, `supersedes`, `derived_from`.
- **Feedback (`outcome`):** `helped`, `irrelevant`, `wrong`, `outdated`, `verified`.
- **Key:** `<tipo>/<nome>` (nome em minúsculas com `-`); key fora do padrão grava com aviso, key de
  item existente nunca muda.
- **Modelo do `content` por subtipo, só avisa:** `rule/decision` → `## Por quê` e
  `## Alternativa descartada`; `rule/pattern` → `Arquivo-modelo:`; `howto/troubleshoot` →
  `## Sintoma`, `## Causa`, `## Solução`; `context/environment` → ao menos um item em `links`.
- Erros de validação sempre dizem **como corrigir** (lista dos valores válidos, a chamada certa).
- `model.py` é **puro** (sem I/O, sem importar serviços) e expõe: as constantes acima;
  `validate_entry(entry: dict) -> tuple[dict, list[str]]` (normaliza e valida uma entrada de
  `item_save`, devolve campos limpos + avisos; lança `ValidationError`);
  `ITEM_FIELDS` (campos aceitos no `item_save`); `taxonomy_markdown() -> str` (tabelas para as
  instruções do MCP, geradas daqui).

## 3. Dados em disco

### 3.1 Item (frontmatter YAML + corpo = `content`)

Ordem dos campos: `key, id, workspace, project, subject?, type, subtype?, scope?, title, status,
tags, links, scope_paths, ttl_days?, keywords, source, origin, verified_at?, verified_commit?,
created_at, updated_at, relations, summary`. Obrigatórios para ler: `id, type, title, summary,
status, created_at, updated_at`. `links` = `[{title, url}]`. Saem `memory_class`, `importance`,
`confidence`, `labels`. Datas: gravadas em UTC com `Z`; na leitura aceita `Z`, offset (`+03:00`,
convertido para UTC) e só data (`2020-01-01`); data inválida é erro daquele arquivo (`parse_errors`),
nunca derruba o resto. Path: `<workspace-slug>/<project-slug>/<key>.md` (sem key:
`.../_sem-key/<id>.md`), como hoje. `ItemRecord` (em `storage/files.py`) e `Item` (em
`services/brain.py`) ganham `subtype, scope, links, origin, verified_at, verified_commit` e perdem
os campos removidos.

### 3.2 `.knowledge.yaml`

Raiz: `{tags: [...]}` (vocabulário). Workspace: `{name, description, scope}`. Project:
`{name, description, scope, subjects: [{name, description?, scope?}]}`. `labels`/`labels_removed`
saem.

### 3.3 Leitura de arquivo antigo (único ponto de compatibilidade)

Em `parse_item_file`, se faltar `subtype`/`origin` ou houver campo antigo: `insight` → `rule` +
`decision`; `procedure` → `howto`; `knowledge` → `howto` + `troubleshoot` + status `review`;
`pattern` → `rule` + `pattern`; `task` → `spec`; `rule` com a palavra `sensivel` em `keywords` →
`rule` + `security` (a palavra sai); status `superseded`/`deprecated` → `archived`; `labels` →
somam-se às `tags`; `memory_class`/`importance`/`confidence` descartados (um `ephemeral` mantém o
`ttl_days`); `origin` ausente em arquivo antigo (tinha `memory_class`) → `user`, nos novos → `agent`.

### 3.4 Estado local (fora do git), por conexão

`usage/<conn>.json`: `{item_id: {shown, opened, last_used_at, helped, wrong, outdated, irrelevant,
verified}}` (lê também o formato antigo `{uses, last_used}`: `uses` vira `opened`);
`searches/<conn>.jsonl`: uma linha por busca que voltou vazia (`{ts, query}`). `repos.json` como hoje.

## 4. Alcance (scope)

- **Scope efetivo** de um item: o primeiro explícito subindo item → subject → project → workspace;
  nada explícito = `scoped`. Calculado no `Snapshot`.
- **`secret` nunca herda:** o scope efetivo de um segredo é só o `scope` do próprio item (padrão
  `scoped`). `SecretService.resolve` (o `knowledge-mcp run`) e a seção Segredos do pacote só
  aceitam segredo de fora do project do repositório quando o item tem `scope` explícito
  `workspace`/`global`. A key resolve do mais perto ao mais longe (project do repo → mesmo
  workspace → global); dois candidatos igualmente próximos são erro (passe o id).
- **Merge/delete preservam o alcance:** `workspace_merge`, `project_merge`, `subject_merge` e
  `subject_delete` gravam como `scope` explícito o scope efetivo anterior dos itens (sem scope
  próprio) que mudariam de alcance, no mesmo commit; a resposta (e a prévia do `subject_delete`)
  traz `scope_changes: {items: n}`. Segredos não entram (nunca herdam).
- O scope controla o que a busca e o pacote **mostram**; não é fronteira de segurança
  (`item_get(ids=...)` e `everywhere=True` leem a conexão inteira) — `secret` é a exceção.
- O item **mora** onde foi salvo; o alcance vem do scope. `workspace_update`/`project_update`/
  `subject_update(scope=...)` mudam o alcance de tudo que herda, sem mover arquivo de item.
- **`services/scope.py`** (novo, resolvedor único; busca, pacote, grafo, `item_get` e `item_save`
  usam só ele):
  - `distance(snapshot, record, viewpoint) -> float | None`, com `viewpoint = (ws_id, pj_id)` do
    repositório ligado (ou `None` para pasta não ligada): mesmo project → `1.0` (qualquer scope);
    outro project do mesmo workspace com scope efetivo `workspace` ou `global` → `0.85`; outro
    workspace (ou pasta não ligada) com scope efetivo `global` → `0.7`; senão `None` (invisível).
  - `reach(snapshot, viewpoint) -> list[tuple[ItemRecord, float]]`.
  - `resolve_key(snapshot, key, viewpoint) -> ItemRecord | None`: acha a key pela mesma cadeia
    (project do repositório, depois o resto do alcance), ou por `id`.
  - `where(record) -> str`: `"<workspace>/<project>"`.

## 5. Busca (`storage/search.py` + `services/item_service.py`)

- Campos indexados e pesos BM25: `title 6, keywords 4, key 3, summary 3, tags 3, subtype 2,
  content 1`. A `key` é tokenizada pelas partes separadas por `/` e `-` (`howto/erro-schema-velho`
  → `howto`, `erro`, `schema`, `velho`), então `item_search("gotcha")` acha `gotcha/windows-which`.
- **Pasta não ligada:** `repo` informado e não ligado na busca vale como sem `repo` (só os globais
  + `suggestion` com `repo(action="link", repo="<o que foi passado>")`); as demais ferramentas
  dão erro com a chamada que resolve.
- **Identificadores**: o tokenizador, além do token inteiro em minúsculas, indexa as partes de
  camelCase, snake_case e pontos (`ItemService.saveBatch` → `itemservice`, `item`, `service`,
  `savebatch`, `save`, `batch`); código de erro (`ERR_CONN_42`) é achado como está. A consulta
  recebe o mesmo tratamento. Mantém: sem acento, radical PT-BR, prefixo, AND com queda para OR.
- **Ranking:** `score = BM25 × distância × (1.5 se `paths` casa `scope_paths`) × (0.6 se status
  `review`) × (1 + 0.1·ln(1 + helped + opened)) × (1 − 0.3·taxa_irrelevant)`; para `origin=user` o
  último fator nunca fica abaixo de 1. `taxa_irrelevant = irrelevant / max(1, shown)`.
- **Resultado** (resumos, nunca o `content` completo): `id, key, type, subtype, title, summary, scope`
  (efetivo), `where`, `status`, `score`, `matched_in` (lista de `title|keywords|key|summary|tags|
  subtype|content|path`), `snippet`; com `paths`, também `excerpt` (até 600 caracteres do `content`) e
  `scope_paths`. Itens fora do project do repositório levam `where` diferente do project ligado.
- **Padrão:** exclui `archived` e vencidos (`ttl_days`); `status=["expired"]` os mostra (com
  `status: "expired"`); `review` entra, depois e marcado.
- **Filtros:** `types, subtypes, status, tags, paths, origin, scope`.
- **API de alto nível** (`ItemService.search`): `item_search(query?, queries?, repo?, workspace?,
  everywhere?, paths?, types?, subtypes?, status?, tags?, origin?, scope?, limit=10)` devolve um
  dicionário: `{results: [...]}`; com `queries` (até 5, 6 é erro "no máximo 5"):
  `{groups: [{query, results}]}`; sem consulta nem `queries` (e com repo): `{groups: [{group, results}]}`
  com `seguranca` (`rule/security`), `regras`, `contexto`, `specs` (spec `active`/`draft`). Pasta não
  ligada: só globais + `suggestion` com a chamada `repo(action="link")`. `workspace=` busca o
  workspace inteiro (todos os projects, qualquer scope) + os globais de fora; `everywhere=True`,
  tudo, distância 1.0; `scope=["global"]` lista os globais.
- **Sinais automáticos:** cada resultado devolvido soma `shown`; `item_get` e os nós do `item_graph`
  somam `opened` e `last_used_at`; busca vazia vai para `searches/<conn>.jsonl`.

## 6. Itens (`ItemService`)

- `save(items, default_location=None)`: lote atômico (um erro desfaz tudo e aponta a entrada);
  `key` → upsert no project (onde o item mora), `id` → atualiza (e, com `workspace`/`project`/
  `subject` novos, move), sem nenhum → cria e devolve `similar`. Campos aceitos: `ITEM_FIELDS` do
  `model.py` + `workspace, project, subject`. Retorno por entrada: `{index, id, key, scope, action:
  created|updated|unchanged, warnings, similar?, has_value?, fill_url?}`. Avisos: modelo do `content`,
  key válida fora do padrão `<tipo>/<nome>`, tag nova (com sugestão parecida). Limites: no máximo 20
  entradas por chamada; `keywords` é texto (lista dá erro); key com espaço ou caractere fora de
  letras, números, `.`, `_`, `-` e `/` é **erro de gravação**, não aviso (maiúscula e `_` só avisam). Segredos como hoje (item `secret` sem valor,
  `fill_url`; valor é recusado; detecção de segredo em item comum recusa).
- `get_many(keys=None, ids=None, ...)`: até 20, key resolvida pela cadeia de alcance do repositório;
  faltando → `{key|id, missing: true}`; soma `opened`.
- `delete(keys=None, ids=None, confirm=False)`:
  - sem `keys`/`ids`: **candidatos** `[{key, id, reason}]` com `reason` ∈ `expired`,
    `archived_90d`, `stale_review_14d`, `unused` (origin `agent`, sem `opened` nem `helped` há 90
    dias), `irrelevant` (origin `agent`, `irrelevant` ≥ 3 e `irrelevant > helped`); **nunca**
    `origin=user`;
  - com `keys`/`ids` e sem `confirm`: prévia; com `confirm=True`: apaga o item e as relações que
    apontam para ele, num commit.
- `feedback(items, repo=None)`: `[{key|id, outcome, note?, query?}]`; `helped`/`irrelevant` só
  somam contador (sem commit no git); `wrong`/`outdated` → status `review` no arquivo, com commit
  (e a `note` anexada ao `content` numa linha `> Revisão <data>: <nota>`); `verified` grava
  `verified_at` (agora) e `verified_commit` (`git rev-parse HEAD` do `repo`, se houver; senão
  ausente) — **não** reativa item em `review`. Retorno `{applied: n, missing: [...]}`.
- Sai `memory_service` (promoção de classe), `label_service`, `maintenance.purge_expired_ephemeral`.

## 7. Relações e grafo

- `RelationService`: `create(items)` e `delete(items)` com `items = [{source, type, target}]`
  (até 20, atômico, source/target por key ou id resolvidos pela cadeia); duplicata é no-op
  (`unchanged`); tipo inválido lista os válidos; `supersedes` marca o alvo `archived`. O arquivo do
  item de origem é republicado.
- `services/graph.py`: `item_graph(keys (≤5), repo?, depth=1 (1–3), limit=20 (máx 100),
  relation_types?, types?, direction="both"|"out"|"in")` →
  `{nodes: [{key, id, type, subtype, title, summary, scope, status, hop}], edges: [{from, type, to}],
  truncated, total_by_hop}`. Vizinhos ordenados por hop, depois sinais, depois `updated_at`; o corte
  por `limit` marca `truncated` e preenche `total_by_hop` com o total real.

## 8. Tags gerenciadas

`tag_list() → [{name, count}]` (inclui `count: 0`); `tag_create(names)`; `tag_update(name, new_name)`
(renomeia em todos os itens e no vocabulário, num commit; se `new_name` existe, mescla);
`tag_delete(names, confirm=False)` (prévia com o número de itens; `confirm=True` remove dos itens e
do vocabulário). Tag nova no `item_save` é criada, com aviso e sugestão de uma existente parecida.
Nomes em kebab-case minúsculo.

## 9. Organização

`workspace_*`, `project_*`, `subject_*` com `list, create, update, merge, delete`: `create` e
`update` aceitam `description` e `scope` (`update` também `new_name`); `merge` e `delete` como hoje
(`delete` com prévia sem `confirm`). `*_list` devolve `[{name, description, scope, items, ...}]`
(project traz também `subjects`). Sem `*_rename` (vira `update`). `repo(action=link|list|unlink|sync)`
e `connection_create/list/delete` como hoje (sem conexão automática).

## 10. Pacote do hook e CLI

- `knowledge-mcp context [--repo] [--paths ...] [--query] [--budget] [--hook claude|cursor]`: mesma
  cadeia de alcance. Seções, nesta ordem: **Em foco** (itens que casam `paths`/`query`, com o começo
  do `content`), **⚠ Em revisão**, **Segurança** (`rule/security`), **Regras `[subtipo]`**,
  **Contexto**, **Como fazer** (só títulos), **Specs ativas** (`active`/`draft`), **Segredos** (estado
  e como usar), **Regras com escopo** (as de `scope_paths` que casam). Linha de item de fora do
  project do repositório marcada com a origem (`[global]` ou `[<workspace>]`). A palavra `sensivel`
  não tem mais efeito (sensível = `rule/security`). Orçamento em tokens, lista o que ficou de fora.
  Sem conexão: texto com o exemplo de `connection_create`; hook nunca derruba a sessão.
- `knowledge-mcp report --json`: `{never_opened_60d, review_over_7d, high_irrelevant,
  empty_searches: [{query, count}], tags_unused}`, cada lista com `key`, `where` e o motivo.
- `recent`, `pending` (fila offline; as entradas gravam pelo `item_save` v2), `link`, `run`
  (`secret/...`) mantidos; `backup` já saiu.
- `health_check()` → `{status, version, connections: [{name, path, ok, parse_errors: [...]}],
  gh_authenticated}`; arquivo `.md` quebrado aparece em `parse_errors`.

## 11. Ferramentas MCP (exatamente 32)

`workspace_{list,create,update,merge,delete}`, `project_{…}`, `subject_{…}`, `repo`, `item_search`,
`item_get`, `item_save`, `item_delete`, `item_feedback`, `item_graph`, `relation_create`,
`relation_delete`, `tag_list`, `tag_create`, `tag_update`, `tag_delete`, `connection_create`,
`connection_list`, `connection_delete`, `health_check`. **Saem** `context_get`, `label_*`, `*_rename`.
Todas aceitam `connection_id` opcional (menos `connection_*` e `health_check`). `mcp/INSTRUCTIONS.md`
é gerado de `model.taxonomy_markdown()` + texto fixo (um teste compara). Cada docstring de tool tem
exemplo e diz o erro comum. Assinaturas dos lotes: `item_save(items, repo?)`,
`item_get(keys?, ids?, repo?, workspace?, project?)`, `item_delete(keys?, ids?, repo?, confirm=False)`,
`item_feedback(items, repo?)`, `item_graph(keys, repo?, depth=1, limit=20, relation_types?, types?,
direction="both")`, `relation_create(items, repo?)`, `relation_delete(items, repo?)`,
`tag_create(names)`, `tag_update(name, new_name)`, `tag_delete(names, confirm=False)`.

## 12. API HTTP e front

- Rotas do FastAPI no modelo v2: itens com `subtype, scope (efetivo e explícito), links, origin,
  verified_at`, sem `labels`/`memory_class`/`importance`/`confidence`; rotas de labels removidas
  (404); `/tags` com contagem; `scope` em workspace/project/subject (create/update); grafo e
  relações no formato do `item_graph`; busca com os filtros novos.
- Front (`api/static`): 5 tipos com subtipo, `scope` com o herdado indicado, marca ⚠ de `review`,
  `links`, `origin`, tags com contagem e o caminho da conexão; sem labels, classe de memória,
  importância nem confiança; o grafo continua o que existe. Sem redesenho visual.

## 13. Fases, donos e dependências

Cada fase só mexe nos arquivos dela e roda **só os testes dela** (a suíte inteira volta na fase 8).
Testes antigos que a fase quebra por mudar o código: atualize ou apague os dela; os que quebram por
dependência de fases futuras ficam para a fase dona.

| Fase | Entrega | Arquivos | Depende |
|---|---|---|---|
| 1 | Modelo, arquivo e alcance | `model.py`, `services/item_file.py`, `storage/files.py`, `services/brain.py`, `services/scope.py`; testes `test_model`, `test_item_file`, `test_scope`, `storage/test_files`, `test_brain_*` | — |
| 2 | Busca | `storage/search.py`; `tests/test_search_v2.py` (+ ajusta `test_item_search`) | 1 |
| 3 | Relações, grafo, tags | `services/relation_service.py`, `services/graph.py`, `services/tag_service.py`; `test_relations*`, `test_graph`, `test_tags*` | 1 |
| 4 | Itens e sinais | `services/item_service.py`, `storage/local_state.py`, `services/secret_service.py`; `test_items*`, `test_segredos`, `test_signals` | 1, 2, 3 |
| 5 | Organização, pacote, CLI | `services/workspace_service.py`, `project_service.py`, `subject_service.py`, `connection_service.py`, `repo_service.py`, `context_service.py` (vira o pacote), `cli.py`, `config.py`; remove `label_service`, `memory_service`, `maintenance` | 4 |
| 6 | MCP | `mcp/tools.py`, `mcp/INSTRUCTIONS.md`, `mcp/instructions.py`, `main.py` | 4, 5 |
| 7 | API e front | `api/**` (rotas, schemas, `static/**`) | 4, 5 |
| 8 | Docs, contratos, suíte verde | `README.md`, `docs/*.md`, `CHANGELOG.md`, `tests/**`, `pyproject.toml`, `Makefile`; `ruff` limpo; suíte inteira verde | 6, 7 |

## 14. Regras de trabalho

- **Ambiente de testes (Windows):** exporte `TMP=C:/Projects/.ksq-tmp TEMP=C:/Projects/.ksq-tmp
  TMPDIR=C:/Projects/.ksq-tmp` antes do `pytest` (o AppData dá `EBADF`); o comando é `python -m
  pytest -q -p no:cacheprovider <arquivos>`. `ruff check <arquivos>` limpo nos que você tocar. Não
  há `mypy` instalado.
- Código e docstrings em PT-BR, no estilo do repositório (docstring de módulo explicando o modelo,
  comentários só do porquê). Sem dependências novas.
- Testes primeiro: para cada resultado da fase, um teste que falha e depois passa. Teste de
  comportamento observável, não de implementação.
- Não reformate código que você não precisa tocar. Não toque em `START.md` nem em
  `run_knowledge_os.sh` (são do usuário, não versionados).
- Não commite: o orquestrador commita por fase. Não rode `git` que mude estado além de `status`/`diff`.
- Termine devolvendo: o que ficou pronto (por resultado), os comandos rodados com a saída resumida,
  os testes que ficaram quebrados **por dependência de fases futuras** (com o motivo) e qualquer
  decisão que você teve que tomar fora deste documento.
