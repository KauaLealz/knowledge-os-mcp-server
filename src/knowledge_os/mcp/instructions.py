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

Memória durável: regras, decisões e o porquê, como fazer, contexto do projeto e specs.

**Onde mora:** workspace = contexto (empresa, cliente, Pessoal); project = repositório;
subject = assunto opcional dentro do project. O item mora no project em que foi salvo.
**Onde vale (`scope`):** `scoped` = só no project; `workspace` = em todos os projects do
workspace; `global` = em qualquer lugar. Sem `scope` no item, herda do subject → project →
workspace (`workspace_update(name, scope=...)` muda o alcance de tudo que herda, sem mover).

**Conexão:** os dados são arquivos Markdown numa pasta git. Sem conexão nada funciona:
`connection_create(name, path[, remote_url])`; `connection_list`, `connection_delete` (não
apaga a pasta). `health_check()` mostra as conexões e os arquivos que não leram.

**Ler:** o pacote do projeto vem injetado no início da sessão. Dúvida:
`item_search(query, repo=".")` (até 5 de uma vez com `queries=[...]`; `paths=[arquivos]` sobe
as regras daqueles arquivos), depois `item_get(keys=[...], repo=".")`; ligações:
`item_graph(keys=[...], repo=".")`. Ao usar um item, diga como foi:
`item_feedback(items=[{key, outcome}], repo=".")`.

**Quando gravar** (`item_save(items=[...], repo=".")`, em lote, `key` estável — regrava sem
duplicar): o usuário enuncia regra, decisão ou preferência (grave na hora, `origin: "user"`);
você destrava algo não óbvio (`howto/troubleshoot`); ao fechar uma mudança, as decisões
(`rule/decision`, com a alternativa descartada) e os passos que se repetem (`howto/procedure`).
Antes de criar, `item_search`; se contradiz um item, `relation_create` com `supersedes`.
Não é item: bug, andamento, medição datada, id de tarefa. `summary` de 1–2 frases com o porquê.

**Quando confirmar:** o que você inferiu (não foi dito pelo usuário) — mostre e espere o "sim".
Destrutivos (`item_delete`, `*_delete`, `tag_delete`) devolvem prévia sem `confirm`; só passe
`confirm=True` com pedido explícito. Tudo é commit no git da conexão: dá para voltar.

**Link e resumo:** toda resposta de item traz `url` (link da UI local); cole-o ao usuário ao
criar ou atualizar uma spec e na entrega. A spec leva `summary` no padrão
`<estado> · <fase n/total> · <branch> · <worktree> · <agente>`. Tags: vocabulário curto e
reaproveitado — `tag_list` antes de criar; 1 a 3 de área/tema, mais as de estado da spec
(`aguardando-aprovacao`, `em-andamento`, `parada`).

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
