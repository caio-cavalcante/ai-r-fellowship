"""Modulo de carga transacional, idempotencia e reconciliacao no PostgreSQL."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

_RAIZ_PROJETO = Path(__file__).resolve().parent.parent
_DUAS_CASAS = Decimal("0.01")
_ZERO = Decimal("0.00")
_TOLERANCIA_RECONCILIACAO = Decimal("0.01")


class ErroCarga(Exception):
    """Excecao lancada em falhas de conexao, carga transacional ou reconciliacao."""


def _sanitizar_mensagem_erro(exc: Exception, segredo: str | None) -> str:
    """Remove eventual exposicao de senha em mensagens de erro."""
    texto = str(exc)
    if segredo:
        texto = texto.replace(segredo, "***")
    return texto


def conectar_banco(env_path: str | Path | None = None) -> Any:
    """Carrega variaveis de ambiente e abre conexao com o PostgreSQL."""
    caminho_env = Path(env_path) if env_path is not None else (_RAIZ_PROJETO / ".env")
    load_dotenv(dotenv_path=caminho_env, override=False)

    variaveis_obrigatorias = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    valores: dict[str, str] = {}
    ausentes: list[str] = []

    for chave in variaveis_obrigatorias:
        bruto = os.getenv(chave)
        if bruto is None or not bruto.strip():
            ausentes.append(chave)
        else:
            valores[chave] = bruto if chave == "PGPASSWORD" else bruto.strip()

    if ausentes:
        raise ErroCarga(
            f"Variaveis de ambiente obrigatorias ausentes ou vazias: {', '.join(ausentes)}."
        )

    try:
        porta = int(valores["PGPORT"])
    except ValueError as exc:
        raise ErroCarga(
            f"PGPORT invalido ({valores['PGPORT']!r}): esperado numero inteiro."
        ) from exc

    if porta < 1 or porta > 65535:
        raise ErroCarga(f"PGPORT fora do intervalo valido (1-65535): {porta}.")

    host = valores["PGHOST"]
    dbname = valores["PGDATABASE"]
    user = valores["PGUSER"]
    password = valores["PGPASSWORD"]

    try:
        return psycopg2.connect(
            host=host,
            port=porta,
            dbname=dbname,
            user=user,
            password=password,
        )
    except psycopg2.Error as exc:
        detalhe = _sanitizar_mensagem_erro(exc, password)
        raise ErroCarga(
            f"Falha ao conectar ao PostgreSQL ({host}:{porta}/{dbname}): {detalhe}"
        ) from exc


def carregar_dados(
    conn: Any,
    produtos: list[dict[str, Any]],
    clientes: list[dict[str, Any]],
    pedidos: list[dict[str, Any]],
    itens: list[dict[str, Any]],
) -> dict[str, int]:
    """Carrega dados em ordem de FKs com idempotencia transacional e queries parametrizadas."""
    sql_produtos = """
        INSERT INTO produtos (produto_id, nome, categoria, preco_base)
        VALUES %s
        ON CONFLICT (produto_id) DO UPDATE SET
            nome = EXCLUDED.nome,
            categoria = EXCLUDED.categoria,
            preco_base = EXCLUDED.preco_base
    """
    sql_clientes = """
        INSERT INTO clientes (id, nome, email, cidade, estado, cadastro_em)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            nome = EXCLUDED.nome,
            email = EXCLUDED.email,
            cidade = EXCLUDED.cidade,
            estado = EXCLUDED.estado,
            cadastro_em = EXCLUDED.cadastro_em
    """
    sql_pedidos = """
        INSERT INTO pedidos (id, cliente_id, data_pedido, status, valor_total, valor_itens, divergente)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            cliente_id = EXCLUDED.cliente_id,
            data_pedido = EXCLUDED.data_pedido,
            status = EXCLUDED.status,
            valor_total = EXCLUDED.valor_total,
            valor_itens = EXCLUDED.valor_itens,
            divergente = EXCLUDED.divergente
    """
    sql_itens = """
        INSERT INTO itens_pedido (pedido_id, linha, produto_id, quantidade, preco_unitario)
        VALUES %s
        ON CONFLICT (pedido_id, linha) DO UPDATE SET
            produto_id = EXCLUDED.produto_id,
            quantidade = EXCLUDED.quantidade,
            preco_unitario = EXCLUDED.preco_unitario
    """

    try:
        linhas_produtos = [
            (p["produto_id"], p["nome"], p["categoria"], p["preco_base"])
            for p in produtos
        ]
        linhas_clientes = [
            (c["id"], c["nome"], c["email"], c["cidade"], c["estado"], c["cadastro_em"])
            for c in clientes
        ]
        linhas_pedidos = [
            (
                p["id"],
                p["cliente_id"],
                p["data_pedido"],
                p["status"],
                p["valor_total"],
                p["valor_itens"],
                p["divergente"],
            )
            for p in pedidos
        ]
        linhas_itens = [
            (
                i["pedido_id"],
                i["linha"],
                i["produto_id"],
                i["quantidade"],
                i["preco_unitario"],
            )
            for i in itens
        ]
        pedido_ids = sorted(
            {p["id"] for p in pedidos} | {i["pedido_id"] for i in itens}
        )
    except (KeyError, TypeError) as exc:
        raise ErroCarga(f"Estrutura de registro invalida para carga: {exc}") from exc

    try:
        with conn:
            with conn.cursor() as cur:
                if linhas_produtos:
                    execute_values(cur, sql_produtos, linhas_produtos)
                if linhas_clientes:
                    execute_values(cur, sql_clientes, linhas_clientes)
                if linhas_pedidos:
                    execute_values(cur, sql_pedidos, linhas_pedidos)
                if pedido_ids:
                    cur.execute(
                        "DELETE FROM itens_pedido WHERE pedido_id = ANY(%s)",
                        (pedido_ids,),
                    )
                if linhas_itens:
                    execute_values(cur, sql_itens, linhas_itens)

                cur.execute("SELECT COUNT(*) FROM produtos")
                total_produtos = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM clientes")
                total_clientes = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM pedidos")
                total_pedidos = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM itens_pedido")
                total_itens = int(cur.fetchone()[0])
    except psycopg2.Error as exc:
        raise ErroCarga(f"Erro ao carregar dados no PostgreSQL: {exc}") from exc

    return {
        "produtos": total_produtos,
        "clientes": total_clientes,
        "pedidos": total_pedidos,
        "itens": total_itens,
    }


def reconciliar_carga(
    conn: Any,
    pedidos_unicos: list[dict[str, Any]],
) -> dict[str, Decimal | int]:
    """Compara contagem e soma de valor_itens entre origem transformada e destino."""
    try:
        contagem_origem = len(pedidos_unicos)
        soma_origem = sum(
            (Decimal(str(p["valor_itens"])) for p in pedidos_unicos),
            _ZERO,
        ).quantize(_DUAS_CASAS, rounding=ROUND_HALF_UP)
        if not soma_origem.is_finite():
            raise ErroCarga("Soma de origem nao finita na reconciliacao.")
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ErroCarga(f"Dados de origem invalidos para reconciliacao: {exc}") from exc

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(valor_itens), 0) FROM pedidos")
            resultado = cur.fetchone()
    except psycopg2.Error as exc:
        raise ErroCarga(f"Erro ao consultar pedidos para reconciliacao: {exc}") from exc

    contagem_destino = int(resultado[0])
    soma_destino = Decimal(str(resultado[1])).quantize(
        _DUAS_CASAS, rounding=ROUND_HALF_UP
    )
    diferenca = abs(soma_origem - soma_destino).quantize(
        _DUAS_CASAS, rounding=ROUND_HALF_UP
    )

    if contagem_origem != contagem_destino:
        raise ErroCarga(
            "Falha na reconciliacao de contagem de pedidos: "
            f"origem={contagem_origem}, destino={contagem_destino}."
        )
    if diferenca > _TOLERANCIA_RECONCILIACAO:
        raise ErroCarga(
            "Falha na reconciliacao de valor_itens: "
            f"origem={soma_origem:.2f}, destino={soma_destino:.2f}, diferenca={diferenca:.2f}."
        )

    return {
        "pedidos_origem": contagem_origem,
        "pedidos_destino": contagem_destino,
        "soma_valor_itens_origem": soma_origem,
        "soma_valor_itens_destino": soma_destino,
        "diferenca": diferenca,
    }
