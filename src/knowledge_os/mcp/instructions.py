"""Instruções do MCP (entram no handshake e no contexto de toda sessão do agente).

Texto fixo curto sobre o modelo (onde o item mora, onde ele vale, quando gravar e confirmar,
fila offline, segredos) seguido das tabelas da taxonomia, geradas de `model.taxonomy_markdown`
para nunca divergirem do que o servidor aceita. `mcp/INSTRUCTIONS.md` é a saída de
`build_instructions()` gravada em disco (é o que `main.py` lê e o wheel empacota); um teste de
contrato confere que os dois são iguais. Para regravar:

    python -c "from knowledge_os.mcp.instructions import write; write()"
"""

from __future__ import annotations

from pathlib import Path

from knowledge_os.model import taxonomy_markdown

INSTRUCTIONS_FILE = Path(__file__).resolve().parent / "INSTRUCTIONS.md"

_TEXT = """\
# Segundo cérebro (Knowledge OS)

Memória durável: o que seguir, como fazer, o contexto do projeto e o trabalho (planos e o
porquê). Schema mínimo: a nuance e o ciclo vivem em **tags**, não em campos.

**Onde mora (= onde vale):** workspace = contexto (empresa, cliente, Pessoal); project =
repositório/sistema; subject = conceito dentro do project (opcional). O item pode morar em
**qualquer nível** e vale onde mora **e abaixo**: no workspace vale em todos os projects dele;
no project, só nele; no subject, só nele. Não há `scope` — o alcance é a hierarquia.

**Conexão:** os dados são arquivos Markdown numa pasta git. Sem conexão nada funciona:
`connection_create(name, path[, remote_url])`; `connection_list`, `connection_delete` (não
apaga a pasta). `health_check()` mostra as conexões e os arquivos que não leram.

**Ler:** o pacote do projeto vem injetado no início da sessão. Dúvida:
`item_search(query, repo=".")` (até 5 de uma vez com `queries=[...]`; `paths=[arquivos]` sobe
as regras daqueles arquivos), depois `item_get(keys=[...], repo=".")`; ligações:
`item_graph(keys=[...], repo=".")`. Usou um item e ele estava errado ou velho? **Corrija ou
remova** (é git, dá para voltar) — não há feedback.

**Quando gravar** (`item_save(items=[...], repo=".")`, em lote, `key` estável — regrava sem
duplicar): o usuário enuncia uma regra ou preferência (grave na hora); você destrava algo não
óbvio (`howto`); ao fechar uma mudança, o que durar (uma `rule`, um `howto`, o `work` com o
porquê). A nuance vai em **tags** (`decision`, `troubleshoot`, `security`…); o ciclo do `work`
em tags (`draft`, `active`, `done`, `archived`). Antes de criar, `item_search`. Não é item:
bug, medição datada, id de tarefa. `summary` de 1–2 frases com o porquê.

**Quando confirmar:** o que você inferiu (não foi dito pelo usuário) — mostre e espere o "sim".
Destrutivos (`item_delete`, `*_delete`, `tag_delete`) devolvem prévia sem `confirm`; só passe
`confirm=True` com pedido explícito. Tudo é commit no git da conexão: dá para voltar.

**Links:** um item liga a outro item (`relation_create`, `depends_on`/`relates_to`) ou a uma
referência externa (`{url}` ou `{path}` em `links`). Toda resposta de item traz `url` (link da
UI local); cole-o ao usuário ao criar um `work` e na entrega. Tags: vocabulário curto e
reaproveitado — `tag_list` antes de criar; 1 a 3 de área/tema.

**Segredos:** item `secret` (`secret/<nome>`) sem valor; passe ao usuário o `fill_url` da
resposta (ele preenche na UI local). Nunca peça nem grave o valor no chat. Usar:
`knowledge-mcp run --env VAR=secret/<nome> -- <comando>`.

**Sem ligação:** `repo(action="link", repo=".")` (ou `/plumb-setup`). **Fora do ar:** siga,
avise e guarde a entrada do `item_save` em `~/.knowledge-os/pending.jsonl`.

**Organização:** `workspace_*`, `project_*`, `subject_*` (list, create, update, merge,
delete), `repo` (link, list, unlink, sync), `tag_list`/`tag_create`/`tag_update`/`tag_delete`,
`relation_create`/`relation_delete`.

## Taxonomia

"""


def build_instructions() -> str:
    """O texto completo das instruções: o fixo + a taxonomia gerada de `model`."""
    return _TEXT + taxonomy_markdown()


def write(path: Path = INSTRUCTIONS_FILE) -> None:
    """Regrava `INSTRUCTIONS.md` com `build_instructions()`."""
    path.write_text(build_instructions(), encoding="utf-8", newline="\n")
