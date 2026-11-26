"""Modulo de extracao de dados da API local da Verdejar e do catalogo CSV."""

from __future__ import annotations

import csv
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

COLUNAS_PRODUTOS_OBRIGATORIAS = frozenset({"produto_id", "nome", "categoria", "preco_base"})


class ErroExtracao(Exception):
    """Excecao lancada em falhas de extracao da API, leitura CSV ou gravacao de brutos."""


def verificar_saude_api(base_url: str, timeout: float = 5.0) -> bool:
    """Verifica se o endpoint /saude da API esta acessivel e retorna status ok."""
    if not isinstance(base_url, str) or not base_url.strip():
        return False
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        return False

    url = f"{base_url.strip().rstrip('/')}/saude"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return False
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return False

    return isinstance(payload, dict) and payload.get("status") == "ok"


def extrair_recurso_paginado(
    base_url: str,
    rota: str,
    page_size: int = 50,
    timeout: float = 10.0,
) -> tuple[list[dict[str, Any]], int]:
    """Extrai todas as paginas de um recurso paginado da API Verdejar."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise ErroExtracao("URL base da API invalida ou vazia.")
    if not isinstance(rota, str) or not rota.strip("/ "):
        raise ErroExtracao("Rota da API invalida ou vazia.")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise ErroExtracao(f"page_size invalido ({page_size!r}): deve ser inteiro >= 1.")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ErroExtracao("timeout deve ser um numero positivo finito.")

    rota_limpa = rota.strip().strip("/")
    url = f"{base_url.strip().rstrip('/')}/{rota_limpa}"

    registros: list[dict[str, Any]] = []
    paginas_consumidas = 0
    page = 1

    with requests.Session() as sessao:
        while True:
            try:
                resp = sessao.get(
                    url,
                    params={"page": page, "page_size": page_size},
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise ErroExtracao(
                    f"Erro de conexao ao acessar {url} (pagina {page}): {exc}"
                ) from exc

            if resp.status_code != 200:
                try:
                    erro_json = resp.json()
                    detalhe = (
                        erro_json.get("erro")
                        if isinstance(erro_json, dict) and "erro" in erro_json
                        else resp.text[:200]
                    )
                except ValueError:
                    detalhe = resp.text[:200]

                if resp.status_code == 404:
                    raise ErroExtracao(
                        f"Pagina ou rota inexistente (HTTP 404) em {url} (pagina {page}): {detalhe}"
                    )
                raise ErroExtracao(
                    f"Erro HTTP {resp.status_code} em {url} (pagina {page}): {detalhe}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise ErroExtracao(
                    f"Resposta JSON invalida em {url} (pagina {page}): {exc}"
                ) from exc

            if not isinstance(payload, dict):
                raise ErroExtracao(
                    f"Envelope JSON invalido em {url} (pagina {page}): esperado objeto JSON."
                )

            items = payload.get("items")
            total_pages = payload.get("total_pages")

            if not isinstance(items, list):
                raise ErroExtracao(
                    f"Campo 'items' ausente ou invalido em {url} (pagina {page})."
                )
            if (
                not isinstance(total_pages, int)
                or isinstance(total_pages, bool)
                or total_pages < 0
            ):
                raise ErroExtracao(
                    f"Campo 'total_pages' ausente ou invalido em {url} (pagina {page})."
                )
            if not all(isinstance(item, dict) for item in items):
                raise ErroExtracao(
                    f"Elementos de 'items' invalidos em {url} (pagina {page}): esperado lista de objetos."
                )

            registros.extend(items)
            paginas_consumidas += 1

            if page >= total_pages:
                break
            page += 1

    return registros, paginas_consumidas


def ler_produtos_csv(caminho_csv: str | Path) -> list[dict[str, Any]]:
    """Le o catalogo de produtos em CSV UTF-8 e converte produto_id (int) e preco_base (Decimal)."""
    caminho = Path(caminho_csv)
    produtos: list[dict[str, Any]] = []

    try:
        with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
            leitor = csv.DictReader(arquivo)
            if not leitor.fieldnames or not COLUNAS_PRODUTOS_OBRIGATORIAS.issubset(
                set(leitor.fieldnames)
            ):
                raise ErroExtracao(
                    f"Cabecalho invalido em {caminho}: esperado colunas {sorted(COLUNAS_PRODUTOS_OBRIGATORIAS)}."
                )

            for indice_linha, linha in enumerate(leitor, start=2):
                if None in linha:
                    raise ErroExtracao(
                        f"Colunas extras inesperadas na linha {indice_linha} de {caminho}."
                    )
                if any(linha.get(col) is None for col in COLUNAS_PRODUTOS_OBRIGATORIAS):
                    raise ErroExtracao(
                        f"Coluna ausente na linha {indice_linha} de {caminho}."
                    )

                produto_id = int(str(linha["produto_id"]).strip())
                if produto_id <= 0:
                    raise ErroExtracao(
                        f"produto_id deve ser positivo na linha {indice_linha} de {caminho}."
                    )
                nome = str(linha["nome"]).strip()
                categoria = str(linha["categoria"]).strip()
                if not nome or not categoria:
                    raise ErroExtracao(
                        f"Nome ou categoria vazio na linha {indice_linha} de {caminho}."
                    )
                preco_base = Decimal(str(linha["preco_base"]).strip()).quantize(
                    Decimal("0.01")
                )
                if not preco_base.is_finite() or preco_base <= 0:
                    raise ErroExtracao(
                        f"preco_base deve ser finito e positivo na linha {indice_linha} de {caminho}."
                    )

                produtos.append(
                    {
                        "produto_id": produto_id,
                        "nome": nome,
                        "categoria": categoria,
                        "preco_base": preco_base,
                    }
                )
    except ErroExtracao:
        raise
    except (OSError, csv.Error, ValueError, InvalidOperation, KeyError, TypeError) as exc:
        raise ErroExtracao(f"Falha ao ler catalogo de produtos {caminho}: {exc}") from exc

    return produtos


def salvar_brutos(
    diretorio_brutos: str | Path,
    clientes: list[dict[str, Any]],
    pedidos: list[dict[str, Any]],
) -> None:
    """Preserva os payloads brutos de clientes e pedidos em JSON UTF-8 antes da transformacao."""
    destino = Path(diretorio_brutos)
    try:
        destino.mkdir(parents=True, exist_ok=True)
        with (destino / "clientes.json").open("w", encoding="utf-8", newline="\n") as f_cli:
            json.dump(clientes, f_cli, ensure_ascii=False, indent=2)
        with (destino / "pedidos.json").open("w", encoding="utf-8", newline="\n") as f_ped:
            json.dump(pedidos, f_ped, ensure_ascii=False, indent=2)
    except (OSError, TypeError, ValueError) as exc:
        raise ErroExtracao(f"Falha ao salvar dados brutos em {destino}: {exc}") from exc
