"""Orquestrador principal do pipeline ETL da Verdejar."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROJETO))

import psycopg2
from dotenv import load_dotenv

from etl.carga import ErroCarga, carregar_dados, conectar_banco, reconciliar_carga
from etl.extracao import (
    ErroExtracao,
    extrair_recurso_paginado,
    ler_produtos_csv,
    salvar_brutos,
    verificar_saude_api,
)
from etl.transformacao import (
    ErroTransformacao,
    transformar_clientes,
    transformar_pedidos,
    transformar_produtos,
)


def executar_etl() -> list[str]:
    """Executa extracao, preservacao de brutos, transformacao, carga e reconciliacao."""
    caminho_env = _RAIZ_PROJETO / ".env"
    load_dotenv(dotenv_path=caminho_env, override=False)

    base_url = os.getenv("VERDEJAR_API_URL", "http://127.0.0.1:8000").strip()
    if not verificar_saude_api(base_url):
        raise ErroExtracao(
            f"API Verdejar inacessivel ou sem resposta saudavel em {base_url}."
        )

    clientes_brutos, paginas_clientes = extrair_recurso_paginado(
        base_url, "clientes", page_size=50
    )
    pedidos_brutos, paginas_pedidos = extrair_recurso_paginado(
        base_url, "pedidos", page_size=50
    )
    produtos_brutos = ler_produtos_csv(_RAIZ_PROJETO / "insumos" / "dados" / "produtos.csv")
    salvar_brutos(_RAIZ_PROJETO / "brutos", clientes_brutos, pedidos_brutos)

    produtos_limpos = transformar_produtos(produtos_brutos)
    clientes_limpos, cont_clientes = transformar_clientes(clientes_brutos)
    pedidos_limpos, itens_limpos, cont_pedidos = transformar_pedidos(pedidos_brutos)

    conn = conectar_banco(env_path=caminho_env)
    try:
        cont_carga = carregar_dados(
            conn,
            produtos_limpos,
            clientes_limpos,
            pedidos_limpos,
            itens_limpos,
        )
        reconciliacao = reconciliar_carga(conn, pedidos_limpos)
    finally:
        conn.close()

    linhas = [
        f"extracao: clientes paginas={paginas_clientes} registros={len(clientes_brutos)}",
        f"extracao: pedidos paginas={paginas_pedidos} registros_brutos={len(pedidos_brutos)}",
        (
            f"transformacao: pedidos_unicos={cont_pedidos['pedidos_unicos']} "
            f"repetidos_descartados={cont_pedidos['repetidos_descartados']}"
        ),
        (
            f"transformacao: emails_nulos={cont_clientes['emails_nulos']} "
            f"estados_padronizados={cont_clientes['estados_padronizados']} "
            f"datas_convertidas={cont_pedidos['datas_convertidas']} "
            f"valores_convertidos={cont_pedidos['valores_convertidos']}"
        ),
        (
            f"carga: clientes={cont_carga['clientes']} "
            f"produtos={cont_carga['produtos']} "
            f"pedidos={cont_carga['pedidos']} "
            f"itens={cont_carga['itens']}"
        ),
        (
            "reconciliacao: "
            f"soma_valor_itens_origem={reconciliacao['soma_valor_itens_origem']:.2f} "
            f"soma_valor_itens_destino={reconciliacao['soma_valor_itens_destino']:.2f} "
            f"diferenca={reconciliacao['diferenca']:.2f}"
        ),
        (
            f"divergentes: {cont_pedidos['divergentes']} "
            "pedidos com valor_total diferente da soma dos itens"
        ),
    ]
    for linha in linhas:
        print(linha, flush=True)
    return linhas


def main() -> int:
    """Ponto de entrada CLI com tratamento limpo de erros em texto simples."""
    try:
        executar_etl()
    except (ErroExtracao, ErroTransformacao, ValueError, ErroCarga, psycopg2.Error) as exc:
        mensagem = " ".join(str(exc).splitlines()).strip()
        print(f"erro: {mensagem}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
