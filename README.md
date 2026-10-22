# knowledge-os-mcp-server

> Servidor [MCP](https://modelcontextprotocol.io) de **memória durável** (um "segundo cérebro") para agentes: guarda regras, decisões e o porquê, how-tos, contexto e specs como **arquivos Markdown numa pasta git** sua, e os devolve ao agente com baixo custo de contexto.

## O que faz

A memória vive como arquivos `.md` (com frontmatter) numa pasta git que **você** escolhe — é sua, versionada, inspecionável. O agente consulta antes de agir e grava o que dura. Cinco tipos de item: `rule`, `howto`, `context`, `work`, `secret`. O alcance vem da hierarquia **workspace → project → subject**.

As **31 tools** se agrupam em:

| Área | Tools | Para quê |
|------|-------|----------|
| Itens | `item_search`, `item_get`, `item_save`, `item_delete`, `item_graph` | Buscar, ler, gravar (idempotente por `key`), remover e navegar links entre itens. |
| Hierarquia | `workspace_*`, `project_*`, `subject_*` (list/create/update/merge/delete) | Organizar onde cada item vale (empresa/cliente → repositório → conceito). |
| Relações & tags | `relation_create/delete`, `tag_list/create/update/delete` | Ligar itens (`depends_on`/`relates_to`) e dar nuance por tags. |
| Repositório | `repo` (`link`/`list`/`unlink`/`sync`) | Ligar o repo em que você trabalha a um workspace/project. |
| Conexão & saúde | `connection_create/list/delete`, `health_check` | Criar/listar a pasta git de dados e checar o estado do servidor. |

## Taxonomia dos itens

| Tipo | Guarda |
|---|---|
| `rule` | o que deve ser seguido + o porquê (convenção, decisão, regra de negócio) |
| `howto` | passos repetíveis ou diagnóstico (sintoma/causa/solução) |
| `context` | pano de fundo: produto, mapa, stack, glossário, ambiente |
| `work` | o trabalho: plano/spec + decisões (o porquê durável); ciclo por tag |
| `secret` | referência a um segredo (sem o valor) |

| Campo | Valores |
|---|---|
| tags de ciclo | `draft`, `active`, `done`, `archived` |
| tags de nuance (base, extensível) | `decision`, `troubleshoot`, `security`, `pattern`, `map`, `glossary`, `product`, `environment`, `business`, `process` |
| link item→item (`rel`) | `depends_on`, `relates_to` |

Key: `<tipo>/<nome>` (nome em minúsculas com `-`); fora do padrão grava com aviso, e a key de um item existente nunca muda.

Alcance: o item vale onde mora na hierarquia (workspace → project → subject) e abaixo. Não há `scope`, `status`, `subtype`, `origin` nem expiração — a nuance e o ciclo vão em `tags`.

`links` (unificado): `{item, rel}` liga a outro item; `{url[, title]}` a uma URL; `{path}` a um arquivo/glob do repositório.

## Requisitos

- **Python 3.12+**.
- **git** (CLI) — obrigatório: cada "conexão" é um repositório git e cada escrita é um commit.
- Opcionais: **`gh`** autenticado (só para conexões com `remote_url` e revisão por PR); **keyring do SO** (só se usar itens `secret`).

## Instalação

```bash
uv tool install knowledge-os-mcp-server      # disponibiliza o comando `knowledge-mcp`
# (alternativa: pip install knowledge-os-mcp-server)
```

## Configuração

### 1. Registre no cliente MCP

**Claude Code:**

```bash
claude mcp add --scope user knowledge-os -e LOG_LEVEL=WARNING -- knowledge-mcp
```

**Cursor** (`~/.cursor/mcp.json`) e similares:

```json
{
  "mcpServers": {
    "knowledge-os": {
      "command": "knowledge-mcp",
      "env": { "LOG_LEVEL": "WARNING" }
    }
  }
}
```

O servidor fala por **stdio**; não precisa de args. (Se preferir não instalar, use `"command": "uvx"`, `"args": ["--from", "knowledge-os-mcp-server", "knowledge-mcp"]`.)

### 2. Crie a primeira pasta de dados e ligue seu repo

Nada funciona sem ao menos uma **conexão** (a pasta git dos dados). Pelo agente, uma vez:

- `connection_create(name, path)` — cria/usa a pasta git onde a memória será guardada.
- Dentro do repositório em que você trabalha: `repo(action="link", repo=".")` — o *project* passa a ser esse repo; o *workspace*, o dono do remote.

### Variáveis de ambiente (todas opcionais)

| Variável | Efeito | Default |
|----------|--------|---------|
| `LOG_LEVEL` | Nível de log (recomende `WARNING` nos clientes MCP). | `INFO` |
| `KNOWLEDGE_OS_HOME` | Estado local da máquina (conexões, cache) — **não** guarda itens. | `~/.knowledge-os` |
| `KNOWLEDGE_OS_UI` | `1` sobe a UI local em `127.0.0.1:8765` junto com o servidor; `0` desliga. | `1` |

> **Não** coloque `KNOWLEDGE_OS_VAULT_KEY` na config do MCP nem no ambiente do agente — ela é a chave mestra do cofre de segredos e só serve para CI/máquinas sem keyring.

## Segurança

- Os dados são seus arquivos git — nada sai da sua máquina; a UI local escuta só em loopback.
- `item_search` devolve resumos, nunca o `content` completo por acidente.
- Itens `secret` ficam **cifrados** fora do git, na pasta `.secrets/` da conexão; a chave vive no keyring do SO.
- Operações destrutivas (`*_delete`) devolvem prévia e só executam com `confirm=True`.
