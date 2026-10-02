# Knowledge OS MCP — System Instructions

Este documento é o **mapa mental** do servidor: o que existe, como as peças se
encaixam e como escolher o tool certo. Cada tool tem seu próprio docstring
(Use quando / Retorna / Exemplo / Notas); passo a passo de tarefas completas
fica em `docs/MCP_USAGE.md`. Não repita aqui o que está lá.

## O que é

Knowledge OS é um **servidor MCP** que expõe uma base de conhecimento
pessoal/corporativa como tools. Você guarda conhecimento estruturado, busca por
texto e liga ideias entre si. A base sobrevive entre conversas: o que você
grava hoje pode ser recuperado amanhã.

Hierarquia (de cima para baixo):

```
Connection  (qual banco)
 └── Workspace  (contexto grande)
      └── Domain  (tópico)
           └── Item  (unidade de conhecimento)
                ├── Tags / Labels
                ├── Artifacts (arquivos anexados)
                └── Relations (ligações com outros items)
```

## Conceitos-chave

### Connection
- Aponta para um banco de dados: SQLite local, PostgreSQL ou MySQL.
- A connection **default** é o **catálogo** (id `default`): o SQLite `knowledge.db`
  no home de dados. Existe desde a primeira execução, é reservada (não aparece em
  `connections` no JSON, não se remove nem se edita) e aceita `MCP_DB_PATH` como override.
- Os dados vivem no **home** (`KNOWLEDGE_OS_HOME`, padrão `~/.knowledge-os`):
  `connections.json`, `knowledge.db`, `artifacts/`, `exports/` e `backups/`.
  Não dependem do diretório onde o servidor foi iniciado.
- As demais connections ficam em `<home>/connections.json`; criadas/consultadas via `connection_*`.
- Quase todo tool aceita `connection_id` opcional. **Sem ele, usa a default.**
- Ids de connection: minúsculas, números, `-` e `_` (ex.: `postgres_prod`).

### Workspace
- Contexto grande de conhecimento: um projeto, um assunto, uma pessoa.
- Identificado pelo **nome** (único). Exemplos: "Python Learning", "Company Wiki".
- Contém N domains.

### Domain
- Tópico específico dentro de um workspace. Exemplos: "Decorators", "DevOps".
- Identificado pelo **nome**, único dentro do workspace.
- Contém N items.

### Item
- A unidade de conhecimento. Campos principais:
  - `title` e `summary` (curtos, é o que `item_search` devolve) e `content` (Markdown completo).
  - `type`: `context`, `rule`, `pattern`, `procedure`, `knowledge`, `insight`, `artifact`.
  - `memory_class`: `ephemeral`, `working`, `longterm`, `canonical` (ver abaixo).
  - `confidence` (0-100), `importance` (0-10), `ttl_days`, `tags`, `labels`.
- Escolha do `type`:

| type | Use para |
|------|----------|
| `rule` | Algo que deve ser sempre/nunca feito |
| `pattern` | Solução recorrente para um problema |
| `procedure` | Passo a passo, checklist |
| `knowledge` | Fato ou explicação de um conceito |
| `insight` | Conclusão, decisão e seu porquê |
| `context` | Pano de fundo de um projeto/situação |
| `artifact` | Item cujo valor principal é um arquivo anexado |

### Classe de memória
Define quanto tempo o conhecimento deve durar. Ordem crescente:

| Classe | Significado | Observação |
|--------|-------------|------------|
| `ephemeral` | Anotação temporária | **Exige `ttl_days`**; renovável com `memory_renew` |
| `working` | Em uso no momento | Padrão seguro para o que ainda não foi validado |
| `longterm` | Conhecimento estabelecido | Destino típico de `memory_promote` |
| `canonical` | Fonte de verdade | Reserve para o que é oficial |

`memory_promote` só **sobe** de classe; nunca rebaixa nem volta a `ephemeral`.
Ao sair de `ephemeral`, o `ttl_days` é removido.

### Relation
- Ligação semântica e **direcionada** entre dois items (`source_id` → `target_id`).
- Tipos: `related_to`, `depends_on`, `implements`, `references`, `supersedes`, `derived_from`.
- Exemplo: "item A `depends_on` item B" significa que A depende de B.

### Tag e Label
- **Tag**: string livre, criada dinamicamente (pode ser passada direto em `item_create`).
- **Label**: lista controlada. Padrão: `official`, `critical`, `experimental`,
  `deprecated`, `reference`. Rode `label_list` antes de usar uma.
- Tags e labels são aplicadas **na criação do item** (`item_create`). Não há tool
  para editá-las num item existente; `item_update` não altera tags nem labels.

### Artifact
- Arquivo local anexado a um item (doc, imagem, código). Copiado para o armazenamento.
- Máximo de **100MB por arquivo**. Os metadados ficam no banco.
- `artifact_get` devolve o conteúdo em base64: confira `file_size` antes.

## Configurar conexões

As connections vivem em `<home>/connections.json` (`~/.knowledge-os/connections.json`
por padrão). Você pode editar o arquivo
à mão ou usar `connection_create`; os tools leem o arquivo do disco a cada
chamada, então **não é preciso reiniciar o servidor**.

### Formato

```json
{
  "version": "1.0",
  "default": "default",
  "connections": [
    {
      "id": "sqlite_extra",
      "name": "SQLite extra",
      "db_type": "sqlite",
      "path": "extra.db",
      "enabled": true
    },
    {
      "id": "postgres_prod",
      "name": "PostgreSQL Produção",
      "db_type": "postgresql",
      "host": "prod.company.com",
      "port": 5432,
      "database": "knowledge_db",
      "username": "dbuser",
      "password": "<senha>",
      "enabled": true
    },
    {
      "id": "mysql_local",
      "name": "MySQL Local",
      "db_type": "mysql",
      "host": "localhost",
      "port": 3306,
      "database": "knowledge",
      "username": "root",
      "password": "<senha>",
      "enabled": false
    }
  ]
}
```

JSON não aceita comentários: não os coloque no arquivo.

### Campos

- `id`: único; minúsculas, números, `-` e `_`.
- `name`: nome amigável.
- `db_type`: `sqlite`, `postgresql` ou `mysql`.
- SQLite usa `path`: relativo, resolve contra o home; absoluto não muda. PostgreSQL e MySQL usam `host`, `port`, `database`,
  `username` e `password`.
- `password`: a senha da connection, em texto no JSON (que fica no home, fora do
  repositório). Os tools nunca a devolvem: `connection_get`/`connection_list` só
  informam `password_set` (true/false).
- `enabled`: `false` desativa a connection sem apagá-la.
- `default` (raiz do arquivo): `id` da connection usada quando o tool é chamado
  sem `connection_id`. `"default"` (o catálogo) ou um `id` da lista.

### Passo a passo

1. Adicione a connection em `<home>/connections.json` (ou chame
   `connection_create`, que não aceita senha).
2. A senha é informada pelo usuário na UI ou editando o campo `password` no JSON.
   Nunca peça nem repita a senha na conversa.
3. Valide com `connection_test` e prepare o banco com `schema_sync`
   (ou `connection_init_db`).
4. Use: `workspace_create(name="Shared", connection_id="postgres_prod")`.

## Convenções de parâmetros

- **Workspace e domain por nome.** Nos tools de domain, `workspace` é o nome.
  Em `item_create` e `item_search`, `workspace` e `domain` aceitam **nome ou id**.
- **Items, relations, tags, labels e artifacts por id** (`item_id`, `relation_id`,
  `tag_id`, `label_id`, `artifact_id`). Obtenha o id no retorno do `*_create`
  ou nos `*_list` / `item_search`.
- **`connection_id` é sempre opcional** nos tools de dados. Em `connection_*`
  ele identifica a connection-alvo (id ou nome).
- Retornos de deleção trazem `status` (`deleted`/`ok`/`not_found`) e `message`.
- Erros (not found, nome duplicado, valor inválido) voltam como erro do tool com
  mensagem explicativa. Leia a mensagem antes de tentar de novo.

## Fluxo típico (modo simples)

```
1. connection_list()                 → conferir a connection default
2. workspace_list()                  → ver o que já existe (vazio no início)
3. workspace_create(name)            → só se o contexto ainda não existe
4. domain_create(workspace, name)    → só se o tópico ainda não existe
5. item_create(workspace, domain, type, memory_class, title, summary, content)
6. item_search(workspace, query)     → achar conhecimento depois
7. item_get(item_id)                 → ler o content completo do resultado
```

**Antes de criar, procure.** Rode `workspace_list`/`domain_list`/`item_search`
para não duplicar contexto, tópico ou conhecimento que já está guardado.

## Fluxo avançado (multi-connections)

```
1. connection_create(name, db_type, url)  → registra o banco novo
2. connection_test(connection_id)         → valida a conectividade
3. connection_init_db(connection_id)      → cria o schema no banco novo
4. workspace_list(connection_id=...)      → vazio no início
5. migrate_workspaces(from, to, mode)     → copia o conhecimento entre bancos
```

Depois de registrar uma connection, **passe `connection_id` em cada chamada**
para operar nela. A connection default não muda sozinha.

## Escolher o tool certo

| Objetivo | Tool(s) | Observação |
|----------|---------|------------|
| Ver connections | `connection_list`, `connection_get` | Comece sempre por aqui em sessão nova |
| Adicionar banco remoto | `connection_create` → `connection_test` → `connection_init_db` | Nessa ordem |
| Pausar/renomear connection | `connection_update` | Não altera a URL |
| Remover connection | `connection_delete` | Peça confirmação ao usuário |
| Mover dados entre bancos | `migrate_workspaces` | `replace` apaga o destino; `merge` une |
| Criar contexto | `workspace_create` | Novo projeto/assunto |
| Listar/ler contextos | `workspace_list`, `workspace_get` | |
| Estruturar tópico | `domain_create`, `domain_list`, `domain_get` | Dentro de um workspace |
| Guardar conhecimento | `item_create` | Markdown + metadados |
| Buscar | `item_search` | Texto completo; **ponto de partida** para ler |
| Ler conteúdo | `item_get` | `item_search` nunca devolve `content` |
| Corrigir conhecimento | `item_update` | Só os campos informados mudam |
| Mudar durabilidade | `memory_promote`, `memory_renew` | Subir classe / estender TTL |
| Conectar ideias | `relation_create`, `relation_list` | Grafo entre items |
| Catalogar | `tag_create`/`tag_list`, `label_create`/`label_list` | Vocabulário da connection |
| Anexar arquivos | `artifact_attach`, `artifact_list`, `artifact_get` | Até 100MB |
| Backup / mover | `workspace_export`, `workspace_import` | ZIP; import cria workspace novo |
| Backup parcial | `domain_export`, `domain_import` | Um tópico |
| Remover | `*_delete` | Destrutivo, veja Segurança |
| Diagnóstico | `health_check` | Valida servidor, banco e schema |

## Como buscar bem

1. `item_search` exige `workspace`. Se não souber qual, rode `workspace_list` e
   escolha pelo nome, ou busque em mais de um.
2. Comece com poucas palavras-chave (o índice é full-text), depois afine com
   `domain`, `types` e `memory_classes`.
3. Os resultados vêm ordenados por `importance`, `confidence`, `access_count` e
   `updated_at`. Dê `importance` e `confidence` honestos ao criar: é o que faz
   o conhecimento certo aparecer primeiro.
4. O resultado traz `id`, `title`, `summary` e `score`. Se o `summary` basta,
   não chame `item_get`; se precisa do texto completo, chame.
5. Busca vazia não prova que o conhecimento não existe: tente sinônimos e
   outro `domain` antes de concluir.

## Boas práticas ao gravar

- **Um conhecimento por item.** Itens pequenos e focados são mais fáceis de
  achar e de relacionar.
- **`summary` informativo** (uma ou duas frases): é o que aparece nas buscas.
- **`content` em Markdown**, com exemplos de código quando houver.
- **Reaproveite tags** (`tag_list`) em vez de criar variantes ("async" e "asyncio").
- **Substituiu algo?** Crie o novo item e ligue com `supersedes` ao antigo, em
  vez de apagar o histórico.
- **Defina a memória conscientemente:** na dúvida, `working`; promova para
  `longterm` quando se provar útil; `canonical` só para o que é oficial.

## Segurança

- **Senhas de banco** ficam no campo `password` da connection, no
  `<home>/connections.json` (fora do repositório). Nunca peça, cole ou repita uma senha
  na conversa: o usuário a informa na UI ou no JSON. Os tools nunca devolvem a senha
  (a URL volta redigida; use `password_set` para saber se existe).
- **URLs e configuração** das connections são persistidas em texto puro em
  `<home>/connections.json`, localmente. Não versione esse arquivo.
- **Operações destrutivas** (`*_delete`, `migrate_workspaces` com `mode="replace"`):
  confirme com o usuário antes e, se houver dúvida, faça `workspace_export`
  primeiro. Deletar workspace ou domain leva os items junto.
- **Arquivos locais**: `artifact_attach`, `workspace_import` e `domain_import`
  leem caminhos do disco. Use só caminhos que o usuário indicou.
- **Permissionamento e auditoria** não existem na v0.1: todo agente conectado
  tem acesso total às connections configuradas.

## Quando algo falha

| Sintoma | Primeira ação |
|---------|---------------|
| Connection não encontrada | `connection_list` e use o id exato |
| Workspace/domain não encontrado | `workspace_list` / `domain_list` e use o nome exato |
| Não conecta ao banco | `connection_test`; confira a URL e a senha (`password_set`) |
| Tabelas ausentes / erro de schema | `connection_init_db`, depois `health_check` |
| Nome duplicado ao criar | Já existe: use `*_get` / `*_list` e reaproveite |
| `ephemeral` rejeitado | Faltou `ttl_days` |

Para o passo a passo de tarefas completas (guardar e buscar, migrar bancos,
relacionar ideias, backup) e a tabela de troubleshooting detalhada, veja
`docs/MCP_USAGE.md`.
