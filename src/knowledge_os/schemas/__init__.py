"""Modelos Pydantic da API HTTP (v2).

As entradas são finas de propósito: aceitam o que vier (inclusive campo desconhecido) e deixam
a validação para os serviços e o `model.py`, que dizem como corrigir (lista dos valores
válidos). Assim a API devolve a mesma mensagem que o MCP para o mesmo erro.
"""
