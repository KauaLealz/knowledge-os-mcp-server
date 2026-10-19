"""Schemas Pydantic de tags gerenciadas (v2): lista com contagem, criar, renomear/mesclar."""

from pydantic import BaseModel


class TagRow(BaseModel):
    """Uma tag e quantos itens a usam (`count: 0` = só no vocabulário)."""

    name: str
    count: int


class TagCreate(BaseModel):
    """`POST /tags`: nomes (normalizados para kebab-case pelo serviço)."""

    names: list[str]


class TagUpdate(BaseModel):
    """`PUT /tags/{name}`: renomeia em todos os itens; se `new_name` já existe, mescla."""

    new_name: str
