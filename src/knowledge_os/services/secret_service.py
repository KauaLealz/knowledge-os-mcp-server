"""Segredos como itens do cérebro: o agente cria vazio, o usuário preenche pela UI local.

O item `secret` é um arquivo como os outros, só com metadados. O valor entra só pela UI
(PUT /api/items/{id}/secret), cifrado em `<pasta da conexão>/.secrets/<item_id>.enc` (pasta
no `.git/info/exclude` da cópia: nunca vai para o git), e sai só por `resolve`, que o
`knowledge-mcp run` usa para entregar ao processo filho. `has_value` = esse arquivo existe.
Nada aqui devolve o valor a uma ferramenta MCP ou rota.
"""

from typing import Any
from urllib.parse import quote

from knowledge_os.config import UI_DEFAULT_PORT
from knowledge_os.exceptions import NotFoundError, StorageError, ValidationError
from knowledge_os.services import scope, vault
from knowledge_os.services.brain import SECRETS_DIRNAME, Brain, Item
from knowledge_os.services.secret_run import MIN_REDACT
from knowledge_os.storage.access import git_for

MAX_VALUE_CHARS = 32768
EXCLUDE_LINE = f"{SECRETS_DIRNAME}/"


def fill_url(item: Any, connection_id: str) -> str:
    """Link da UI local direto no item, onde o usuário preenche o valor."""
    conn = quote(connection_id, safe="")
    return (f"http://127.0.0.1:{UI_DEFAULT_PORT}/ui/#/c/{conn}/w/{item.workspace_id}"
            f"/p/{item.project_id}/i/{item.id}")


class SecretService:
    def __init__(self, connection_id: str | None = None) -> None:
        self._connection_id = connection_id

    @staticmethod
    def _secret_item(brain: Brain, item_id: str) -> Item:
        record = brain.snapshot.get(item_id)
        if record is None:
            raise NotFoundError(f"Item não encontrado: {item_id}")
        if record.type != "secret":
            raise ValidationError("Só um item do tipo secret guarda valor")
        return brain.view(record)

    def set_value(self, item_id: str, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValidationError("Informe o valor")
        if len(value) < MIN_REDACT:
            raise ValidationError(
                f"Valor curto demais (mínimo {MIN_REDACT} caracteres): a saída do "
                "knowledge-mcp run não conseguiria escondê-lo."
            )
        if len(value) > MAX_VALUE_CHARS:
            raise ValidationError(f"Valor grande demais (máximo {MAX_VALUE_CHARS} caracteres)")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValidationError("O valor tem caractere inválido (UTF-16 solto)") from None

        brain = Brain(self._connection_id)
        self._secret_item(brain, item_id)
        secrets_dir = brain.root / SECRETS_DIRNAME
        first = not any(secrets_dir.glob("*.enc")) if secrets_dir.is_dir() else True
        token = vault.encrypt(value, bound_to=item_id, create=first)
        try:
            # `info/exclude` e não `.gitignore`: um `.gitignore` mudado e não commitado seria
            # desfeito por reset/checkout do publish e travaria o pull.
            git_for(brain.conn).ensure_excluded(EXCLUDE_LINE)
            path = brain.secret_path(item_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token, encoding="utf-8")
        except OSError:
            # A mensagem do sistema pode trazer o caminho; o valor nunca, mas fica genérica.
            raise StorageError("Falha ao gravar o valor cifrado na pasta da conexão") from None

    def clear_value(self, item_id: str) -> None:
        brain = Brain(self._connection_id)
        self._secret_item(brain, item_id)
        brain.secret_path(item_id).unlink(missing_ok=True)

    def describe(self, item_ids: list[str]) -> dict[str, dict[str, Any]]:
        """{id: {has_value, fill_url}} dos itens `secret` entre os ids (para o item_save)."""
        if not item_ids:
            return {}
        brain = Brain(self._connection_id)
        out = {}
        for item_id in item_ids:
            record = brain.snapshot.get(item_id)
            if record is not None and record.type == "secret":
                item = brain.view(record)
                out[item_id] = {"has_value": item.has_value, "fill_url": fill_url(item, brain.cid)}
        return out

    def resolve(self, repo: str, key: str) -> tuple[Item, str]:
        """(item, valor) do segredo `key` (ou id) no alcance do repo, do mais perto ao mais
        longe: o project ligado; depois outro project do mesmo workspace com `scope: workspace`
        ou `global` explícito no item; depois outro workspace com `scope: global` explícito.

        Segredo nunca herda scope (`Snapshot.effective_scope`): um workspace `global` não
        espalha os segredos dele — só o `scope` do próprio item tira o segredo do project. Dois
        candidatos igualmente próximos com a mesma key são ambíguos: erro que pede o id.

        Conta o uso. Sem item ou sem valor: erro que diz o que fazer, sem rodar nada.
        """
        from knowledge_os.services.repo_service import RepoService

        brain = Brain(self._connection_id)
        link = RepoService(brain.cid).require(repo)
        viewpoint = (link["workspace_id"], link["project_id"])
        found = [(record, weight) for record, weight in scope.reach(brain.snapshot, viewpoint)
                 if record.type == "secret" and record.status == "active"
                 and key in (record.key, record.id)]
        closest = [record for record, weight in found if weight == found[0][1]] if found else []
        if len(closest) > 1:
            places = ", ".join(sorted(scope.where(r) for r in closest))
            raise ValidationError(
                f"Segredo {key} existe em mais de um lugar com o mesmo alcance ({places}): "
                "passe o id do item no lugar da key (item_search mostra o id)."
            )
        item = brain.view(closest[0]) if closest else None
        if item is None:
            raise NotFoundError(
                f"Segredo não encontrado: {key}. A key de um segredo é secret/<nome>. O agente "
                "cria o item (type secret, sem valor) com item_save e passa ao usuário o "
                "link para preencher na UI."
            )
        if not item.has_value:
            raise ValidationError(
                f"Segredo {key} sem valor: peça ao usuário para preencher em "
                f"{fill_url(item, brain.cid)}"
            )
        token = brain.secret_path(item.id).read_text(encoding="utf-8")
        value = vault.decrypt(token, bound_to=item.id)
        brain.track([item.id])
        return item, value
