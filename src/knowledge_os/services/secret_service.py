"""Segredos como itens do cérebro: o agente cria vazio, o usuário preenche pela UI local.

O valor entra só pela UI (PUT /api/items/{id}/secret) e sai só por `resolve`, que o
`knowledge-mcp run` usa para entregar ao processo filho. Nada aqui devolve o valor a uma
ferramenta MCP ou rota.
"""

from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import SQLAlchemyError

from knowledge_os.config import UI_DEFAULT_PORT
from knowledge_os.db.models import DEFAULT_CONNECTION_ID, Item, SecretValue
from knowledge_os.db.session import (
    default_connection_id,
    get_engine,
    get_session,
    run_with_retry,
)
from knowledge_os.exceptions import DatabaseError, NotFoundError, ValidationError
from knowledge_os.services import vault
from knowledge_os.services.secret_run import MIN_REDACT

MAX_VALUE_CHARS = 32768  # o token Fernet (~4/3 do valor) cabe no TEXT de 64 KB do MySQL


def fill_url(item: Item, connection_id: str | None = None) -> str:
    """Link da UI local direto no item, onde o usuário preenche o valor."""
    try:
        conn = connection_id or default_connection_id()
    except Exception:  # noqa: BLE001 - sem connections.json legível, o catálogo
        conn = DEFAULT_CONNECTION_ID
    conn = quote(conn, safe="")
    return (f"http://127.0.0.1:{UI_DEFAULT_PORT}/ui/#/c/{conn}/w/{item.workspace_id}"
            f"/d/{item.domain_id}/i/{item.id}")


class SecretService:
    def __init__(self, engine: Engine | None = None, connection_id: str | None = None) -> None:
        self._engine = engine
        self._connection_id = connection_id

    def _get_engine(self) -> Engine:
        return self._engine if self._engine is not None else get_engine(self._connection_id)

    def _secret_item(self, s: Any, item_id: str) -> Item:
        item = s.get(Item, item_id)
        if item is None:
            raise NotFoundError(f"Item não encontrado: {item_id}")
        if item.type != "secret":
            raise ValidationError("Só um item do tipo secret guarda valor")
        return item

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

        def work() -> None:
            s = get_session(self._get_engine())
            try:
                self._secret_item(s, item_id)
                first = not s.scalar(select(func.count()).select_from(SecretValue))
                token = vault.encrypt(value, bound_to=item_id, create=first)
                row = s.get(SecretValue, item_id)
                if row is None:
                    s.add(SecretValue(item_id=item_id, ciphertext=token))
                else:
                    row.ciphertext = token
                s.commit()
            finally:
                s.close()

        try:
            run_with_retry(work)
        except SQLAlchemyError:
            # A mensagem do SQLAlchemy traz os parâmetros (o texto cifrado): não sobe adiante.
            raise DatabaseError("Falha ao gravar o valor no banco") from None

    def clear_value(self, item_id: str) -> None:
        def work() -> None:
            s = get_session(self._get_engine())
            try:
                self._secret_item(s, item_id)
                row = s.get(SecretValue, item_id)
                if row is not None:
                    s.delete(row)
                s.commit()
            finally:
                s.close()

        run_with_retry(work)

    def describe(self, item_ids: list[str]) -> dict[str, dict[str, Any]]:
        """{id: {has_value, fill_url}} dos itens `secret` entre os ids (para o item_save)."""
        if not item_ids:
            return {}
        s = get_session(self._get_engine())
        try:
            items = s.scalars(select(Item).where(Item.id.in_(item_ids), Item.type == "secret"))
            return {i.id: {"has_value": i.has_value, "fill_url": fill_url(i, self._connection_id)}
                    for i in items}
        finally:
            s.close()

    def resolve(self, repo: str, key: str) -> tuple[Item, str]:
        """(item, valor) do segredo `key` no repo → `Geral` do workspace → `Global`.

        Conta o uso. Sem item ou sem valor: erro que diz o que fazer, sem rodar nada.
        """
        from knowledge_os.services.context_service import ContextService
        from knowledge_os.services.item_service import ItemService
        from knowledge_os.services.repo_service import RepoService

        link = RepoService(self._engine, self._connection_id).require(repo)
        chain = ContextService(self._engine, self._connection_id).domain_chain(link)
        s = get_session(self._get_engine())
        try:
            found = {
                i.domain_id: i for i in s.scalars(select(Item).where(
                    Item.domain_id.in_(chain), (Item.key == key) | (Item.id == key),
                    Item.type == "secret",
                    Item.status == "active"))
            }
            item = next((found[d] for d in chain if d in found), None)
            if item is None:
                raise NotFoundError(
                    f"Segredo não encontrado: {key}. O agente cria o item (type secret, sem "
                    "valor) com item_save e passa ao usuário o link para preencher na UI."
                )
            if not item.has_value:
                raise ValidationError(
                    f"Segredo {key} sem valor: peça ao usuário para preencher em "
                    f"{fill_url(item, self._connection_id)}"
                )
            token = s.scalar(select(SecretValue.ciphertext).where(SecretValue.item_id == item.id))
        finally:
            s.close()
        value = vault.decrypt(token, bound_to=item.id)
        ItemService(self._engine, self._connection_id).track_use([item.id])
        return item, value
