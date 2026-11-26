"""Modulo de transformacao pura e tratamento das armadilhas A1 a A6 da Verdejar."""

from __future__ import annotations

import copy
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

_DUAS_CASAS = Decimal("0.01")
_ZERO = Decimal("0.00")
_TOLERANCIA_DIVERGENCIA = Decimal("0.01")
_RE_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_DATA_BR = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_VALOR_DECIMAL = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_RE_INTEIRO_POSITIVO = re.compile(r"^\+?\d+$")


class ErroTransformacao(ValueError):
    """Excecao lancada em falhas estruturais ou de validacao na transformacao."""


def _validar_int_positivo(valor: Any, campo: str) -> int:
    """Valida que o valor e um inteiro estritamente positivo e nao booleano."""
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise ValueError(f"Campo '{campo}' deve ser inteiro positivo, recebido {valor!r}.")
    return valor


def _validar_texto_nao_vazio(valor: Any, campo: str) -> str:
    """Valida que o valor e uma string nao vazia apos remocao de espacos."""
    if not isinstance(valor, str):
        raise ValueError(f"Campo '{campo}' deve ser texto (str), recebido {type(valor).__name__}.")
    limpo = valor.strip()
    if not limpo:
        raise ValueError(f"Campo '{campo}' nao pode ser vazio.")
    return limpo


def _normalizar_zero(valor: Decimal) -> Decimal:
    """Evita representacao negativa para zero apos quantizacao."""
    return _ZERO if valor == _ZERO else valor


def limpar_email(email: str | None) -> tuple[str | None, bool]:
    """Armadilha A1: normaliza e-mail nulo/vazio para None mantendo o cliente."""
    if email is None:
        return None, True
    if not isinstance(email, str):
        raise ValueError(
            f"Campo 'email' invalido: esperado str ou None, recebido {type(email).__name__}."
        )
    limpo = email.strip()
    if not limpo:
        return None, True
    return limpo, False


def padronizar_estado(estado: str) -> tuple[str, bool]:
    """Armadilha A2: valida sigla UF de 2 letras ASCII e padroniza para maiusculas."""
    if not isinstance(estado, str):
        raise ValueError(
            f"Campo 'estado' invalido: esperado str, recebido {type(estado).__name__}."
        )
    limpo = estado.strip()
    if len(limpo) != 2 or not limpo.isascii() or not limpo.isalpha():
        raise ValueError(
            f"Campo 'estado' invalido ({estado!r}): esperado sigla UF com 2 letras ASCII."
        )
    normalizado = limpo.upper()
    return normalizado, estado != normalizado


def converter_data(data_str: str) -> tuple[date, bool]:
    """Armadilha A3: converte data YYYY-MM-DD ou DD/MM/YYYY para datetime.date."""
    if not isinstance(data_str, str):
        raise ValueError(
            f"Campo de data invalido: esperado str, recebido {type(data_str).__name__}."
        )
    texto = data_str.strip()
    if _RE_DATA_ISO.fullmatch(texto):
        return datetime.strptime(texto, "%Y-%m-%d").date(), False
    if _RE_DATA_BR.fullmatch(texto):
        return datetime.strptime(texto, "%d/%m/%Y").date(), True
    raise ValueError(
        f"Formato de data invalido ({data_str!r}): esperado YYYY-MM-DD ou DD/MM/YYYY."
    )


def converter_valor(valor: str | int | float | Decimal) -> tuple[Decimal, bool]:
    """Armadilha A4: converte numero ou texto com virgula decimal para Decimal(0.01)."""
    if valor is None or isinstance(valor, bool):
        raise ValueError(f"Valor monetario invalido: {valor!r}.")

    tinha_virgula = False
    if isinstance(valor, Decimal):
        if not valor.is_finite():
            raise ValueError(f"Valor Decimal nao finito: {valor!r}.")
        bruto = valor
    elif isinstance(valor, int):
        bruto = Decimal(valor)
    elif isinstance(valor, float):
        if not math.isfinite(valor):
            raise ValueError(f"Valor float nao finito: {valor!r}.")
        bruto = Decimal(str(valor))
    elif isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            raise ValueError("Valor monetario em texto nao pode ser vazio.")
        if "," in texto:
            if "." in texto or texto.count(",") != 1:
                raise ValueError(f"Formato monetario ambiguo ou invalido: {valor!r}.")
            texto_normalizado = texto.replace(",", ".")
            tinha_virgula = True
        else:
            texto_normalizado = texto
        if not _RE_VALOR_DECIMAL.fullmatch(texto_normalizado):
            raise ValueError(f"Valor monetario invalido: {valor!r}.")
        try:
            bruto = Decimal(texto_normalizado)
        except InvalidOperation as exc:
            raise ValueError(f"Valor monetario invalido ({valor!r}): {exc}") from exc
        if not bruto.is_finite():
            raise ValueError(f"Valor monetario nao finito: {valor!r}.")
    else:
        raise ValueError(
            f"Tipo invalido para valor monetario: {type(valor).__name__}."
        )

    quantizado = _normalizar_zero(bruto.quantize(_DUAS_CASAS, rounding=ROUND_HALF_UP))
    return quantizado, tinha_virgula


def desduplicar_pedidos(pedidos: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Armadilha A5: remove pedidos duplicados pelo id mantendo a primeira ocorrencia."""
    if not isinstance(pedidos, list):
        raise ValueError(
            f"Lista de pedidos invalida: esperado list, recebido {type(pedidos).__name__}."
        )

    vistos: set[int] = set()
    pedidos_unicos: list[dict[str, Any]] = []
    repetidos_descartados = 0

    for pedido in pedidos:
        if not isinstance(pedido, dict):
            raise ValueError(
                f"Registro de pedido invalido: esperado dict, recebido {type(pedido).__name__}."
            )
        if "id" not in pedido:
            raise ValueError("Pedido sem campo obrigatorio 'id'.")
        pedido_id = _validar_int_positivo(pedido["id"], "id")
        if pedido_id in vistos:
            repetidos_descartados += 1
        else:
            vistos.add(pedido_id)
            pedidos_unicos.append(copy.deepcopy(pedido))

    return pedidos_unicos, repetidos_descartados


def calcular_itens_e_divergencia(
    itens: list[dict[str, Any]],
    valor_total: Decimal,
) -> tuple[list[dict[str, Any]], Decimal, bool]:
    """Armadilha A6: normaliza itens, gera linha 1-based e calcula divergencia."""
    if isinstance(valor_total, bool) or not isinstance(valor_total, Decimal):
        raise ValueError(
            f"valor_total deve ser Decimal, recebido {type(valor_total).__name__}."
        )
    if not valor_total.is_finite():
        raise ValueError(f"valor_total deve ser Decimal finito, recebido {valor_total!r}.")
    if not isinstance(itens, list):
        raise ValueError(
            f"Lista de itens invalida: esperado list, recebido {type(itens).__name__}."
        )

    valor_total_q = _normalizar_zero(valor_total.quantize(_DUAS_CASAS, rounding=ROUND_HALF_UP))
    itens_normalizados: list[dict[str, Any]] = []
    soma = _ZERO

    for linha, item in enumerate(itens, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Item invalido na linha {linha}: esperado dict, recebido {type(item).__name__}."
            )
        for campo in ("produto_id", "quantidade", "preco_unitario"):
            if campo not in item:
                raise ValueError(f"Item na linha {linha} sem campo obrigatorio '{campo}'.")

        produto_id = _validar_int_positivo(item["produto_id"], "produto_id")
        quantidade = _validar_int_positivo(item["quantidade"], "quantidade")
        preco_unitario, _ = converter_valor(item["preco_unitario"])
        if preco_unitario < _ZERO:
            raise ValueError(
                f"preco_unitario nao pode ser negativo na linha {linha}: {preco_unitario!r}."
            )

        soma += Decimal(quantidade) * preco_unitario
        itens_normalizados.append(
            {
                "linha": linha,
                "produto_id": produto_id,
                "quantidade": quantidade,
                "preco_unitario": preco_unitario,
            }
        )

    valor_itens = _normalizar_zero(soma.quantize(_DUAS_CASAS, rounding=ROUND_HALF_UP))
    divergente = abs(valor_total_q - valor_itens) > _TOLERANCIA_DIVERGENCIA
    return itens_normalizados, valor_itens, divergente


def transformar_produtos(produtos_brutos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza o catalogo de produtos para o esquema de destino sem mutar a entrada."""
    if not isinstance(produtos_brutos, list):
        raise ErroTransformacao(
            f"Lista de produtos invalida: esperado list, recebido {type(produtos_brutos).__name__}."
        )

    produtos_limpos: list[dict[str, Any]] = []
    for indice, produto in enumerate(produtos_brutos):
        if not isinstance(produto, dict):
            raise ErroTransformacao(
                f"Produto invalido no indice {indice}: esperado dict, recebido {type(produto).__name__}."
            )
        for campo in ("produto_id", "nome", "categoria", "preco_base"):
            if campo not in produto:
                raise ErroTransformacao(
                    f"Produto no indice {indice} sem campo obrigatorio '{campo}'."
                )

        raw_pid = produto["produto_id"]
        if isinstance(raw_pid, str):
            texto_pid = raw_pid.strip()
            if not _RE_INTEIRO_POSITIVO.fullmatch(texto_pid):
                raise ErroTransformacao(
                    f"produto_id invalido no indice {indice}: {raw_pid!r}."
                )
            produto_id = _validar_int_positivo(int(texto_pid), "produto_id")
        else:
            produto_id = _validar_int_positivo(raw_pid, "produto_id")

        nome = _validar_texto_nao_vazio(produto["nome"], "nome")
        categoria = _validar_texto_nao_vazio(produto["categoria"], "categoria")
        preco_base, _ = converter_valor(produto["preco_base"])
        if preco_base <= _ZERO:
            raise ErroTransformacao(
                f"preco_base deve ser positivo no indice {indice}: {preco_base!r}."
            )

        produtos_limpos.append(
            {
                "produto_id": produto_id,
                "nome": nome,
                "categoria": categoria,
                "preco_base": preco_base,
            }
        )

    return produtos_limpos


def transformar_clientes(
    clientes_brutos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Transforma clientes aplicando A1 e A2 e validando cadastro_em sem incrementar A3."""
    if not isinstance(clientes_brutos, list):
        raise ErroTransformacao(
            f"Lista de clientes invalida: esperado list, recebido {type(clientes_brutos).__name__}."
        )

    clientes_limpos: list[dict[str, Any]] = []
    emails_nulos = 0
    estados_padronizados = 0

    for indice, cliente in enumerate(clientes_brutos):
        if not isinstance(cliente, dict):
            raise ErroTransformacao(
                f"Cliente invalido no indice {indice}: esperado dict, recebido {type(cliente).__name__}."
            )
        for campo in ("id", "nome", "cidade", "estado", "cadastro_em"):
            if campo not in cliente:
                raise ErroTransformacao(
                    f"Cliente no indice {indice} sem campo obrigatorio '{campo}'."
                )

        cliente_id = _validar_int_positivo(cliente["id"], "id")
        nome = _validar_texto_nao_vazio(cliente["nome"], "nome")
        email_limpo, eh_nulo = limpar_email(cliente.get("email"))
        if eh_nulo:
            emails_nulos += 1

        cidade = _validar_texto_nao_vazio(cliente["cidade"], "cidade")
        estado_limpo, foi_padronizado = padronizar_estado(cliente["estado"])
        if foi_padronizado:
            estados_padronizados += 1

        cadastro_em, _ = converter_data(cliente["cadastro_em"])

        clientes_limpos.append(
            {
                "id": cliente_id,
                "nome": nome,
                "email": email_limpo,
                "cidade": cidade,
                "estado": estado_limpo,
                "cadastro_em": cadastro_em,
            }
        )

    contadores = {
        "total_clientes": len(clientes_limpos),
        "emails_nulos": emails_nulos,
        "estados_padronizados": estados_padronizados,
    }
    return clientes_limpos, contadores


def transformar_pedidos(
    pedidos_brutos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Aplica A5 primeiro e depois A3, A4 e A6 nos pedidos unicos."""
    if not isinstance(pedidos_brutos, list):
        raise ErroTransformacao(
            f"Lista de pedidos invalida: esperado list, recebido {type(pedidos_brutos).__name__}."
        )

    total_brutos = len(pedidos_brutos)
    pedidos_unicos_brutos, repetidos_descartados = desduplicar_pedidos(pedidos_brutos)

    pedidos_limpos: list[dict[str, Any]] = []
    itens_limpos: list[dict[str, Any]] = []
    datas_convertidas = 0
    valores_convertidos = 0
    divergentes = 0

    for indice, pedido in enumerate(pedidos_unicos_brutos):
        for campo in ("id", "cliente_id", "data_pedido", "status", "valor_total", "itens"):
            if campo not in pedido:
                raise ErroTransformacao(
                    f"Pedido unico no indice {indice} sem campo obrigatorio '{campo}'."
                )

        pedido_id = _validar_int_positivo(pedido["id"], "id")
        cliente_id = _validar_int_positivo(pedido["cliente_id"], "cliente_id")
        status = _validar_texto_nao_vazio(pedido["status"], "status")

        data_pedido, era_br = converter_data(pedido["data_pedido"])
        if era_br:
            datas_convertidas += 1

        valor_total, tinha_virgula = converter_valor(pedido["valor_total"])
        if tinha_virgula:
            valores_convertidos += 1

        itens_norm, valor_itens, divergente = calcular_itens_e_divergencia(
            pedido["itens"], valor_total
        )
        if divergente:
            divergentes += 1

        pedidos_limpos.append(
            {
                "id": pedido_id,
                "cliente_id": cliente_id,
                "data_pedido": data_pedido,
                "status": status,
                "valor_total": valor_total,
                "valor_itens": valor_itens,
                "divergente": divergente,
            }
        )

        for item in itens_norm:
            itens_limpos.append(
                {
                    "pedido_id": pedido_id,
                    "linha": item["linha"],
                    "produto_id": item["produto_id"],
                    "quantidade": item["quantidade"],
                    "preco_unitario": item["preco_unitario"],
                }
            )

    contadores = {
        "pedidos_brutos": total_brutos,
        "pedidos_unicos": len(pedidos_limpos),
        "repetidos_descartados": repetidos_descartados,
        "datas_convertidas": datas_convertidas,
        "valores_convertidos": valores_convertidos,
        "divergentes": divergentes,
        "total_itens": len(itens_limpos),
    }
    return pedidos_limpos, itens_limpos, contadores
