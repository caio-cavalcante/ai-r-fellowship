"""Testes unitarios offline para as transformacoes A1 a A6 e orquestradores."""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from etl.extracao import ler_produtos_csv
from etl.transformacao import (
    ErroTransformacao,
    calcular_itens_e_divergencia,
    converter_data,
    converter_valor,
    desduplicar_pedidos,
    limpar_email,
    padronizar_estado,
    transformar_clientes,
    transformar_pedidos,
    transformar_produtos,
)

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
INSUMOS_DADOS = RAIZ_PROJETO / "insumos" / "dados"


class TestArmadilhaA1LimparEmail:
    def test_email_valido_preservado_e_limpo(self) -> None:
        assert limpar_email("  ana.silva1@exemplo.com  ") == (
            "ana.silva1@exemplo.com",
            False,
        )

    @pytest.mark.parametrize("entrada", [None, "", "   ", "\t\n"])
    def test_email_nulo_ou_em_branco_vira_none(self, entrada: str | None) -> None:
        assert limpar_email(entrada) == (None, True)

    @pytest.mark.parametrize("entrada", [123, True, ["a@b.com"]])
    def test_email_tipo_invalido_lanca_value_error(self, entrada: object) -> None:
        with pytest.raises(ValueError):
            limpar_email(entrada)  # type: ignore[arg-type]


class TestArmadilhaA2PadronizarEstado:
    def test_estado_ja_canonico_nao_marca_padronizacao(self) -> None:
        assert padronizar_estado("RS") == ("RS", False)

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("rs", ("RS", True)),
            ("rS", ("RS", True)),
            (" sp ", ("SP", True)),
            (" SP ", ("SP", True)),
            ("rj", ("RJ", True)),
            ("ba", ("BA", True)),
        ],
    )
    def test_estado_padroniza_qualquer_uf_ascii_duas_letras(
        self, entrada: str, esperado: tuple[str, bool]
    ) -> None:
        assert padronizar_estado(entrada) == esperado

    @pytest.mark.parametrize(
        "entrada",
        [None, "", "   ", "S", "SAO", "12", "R$", "ÁB", 42],
    )
    def test_estado_invalido_lanca_value_error(self, entrada: object) -> None:
        with pytest.raises(ValueError):
            padronizar_estado(entrada)  # type: ignore[arg-type]


class TestArmadilhaA3ConverterData:
    def test_data_iso_retorna_date_e_flag_false(self) -> None:
        assert converter_data("2026-02-19") == (date(2026, 2, 19), False)

    def test_data_brasileira_retorna_date_e_flag_true(self) -> None:
        assert converter_data(" 19/02/2026 ") == (date(2026, 2, 19), True)

    @pytest.mark.parametrize(
        "entrada",
        [
            "31/02/2026",
            "2026-13-01",
            "2026/02/19",
            "19-02-2026",
            "2026-2-9",
            "",
            "   ",
            None,
            20260219,
        ],
    )
    def test_data_invalida_lanca_value_error(self, entrada: object) -> None:
        with pytest.raises(ValueError):
            converter_data(entrada)  # type: ignore[arg-type]


class TestArmadilhaA4ConverterValor:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("125,84", (Decimal("125.84"), True)),
            (" 125,84 ", (Decimal("125.84"), True)),
            ("-1,84", (Decimal("-1.84"), True)),
            ("94.34", (Decimal("94.34"), False)),
            (94.34, (Decimal("94.34"), False)),
            (-1.84, (Decimal("-1.84"), False)),
            (10, (Decimal("10.00"), False)),
            (Decimal("12.345"), (Decimal("12.35"), False)),
            (Decimal("-0.001"), (Decimal("0.00"), False)),
        ],
    )
    def test_valor_valido_converte_e_sinaliza_virgula(
        self, entrada: str | int | float | Decimal, esperado: tuple[Decimal, bool]
    ) -> None:
        assert converter_valor(entrada) == esperado

    @pytest.mark.parametrize(
        "entrada",
        [
            True,
            False,
            None,
            "",
            "   ",
            "abc",
            "1.234,56",
            "12,34,56",
            "12.34.56",
            "1_000",
            float("nan"),
            float("inf"),
            float("-inf"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
        ],
    )
    def test_valor_invalido_lanca_value_error(self, entrada: object) -> None:
        with pytest.raises(ValueError):
            converter_valor(entrada)  # type: ignore[arg-type]


class TestArmadilhaA5DesduplicarPedidos:
    def test_mantem_primeira_ocorrencia_e_ordem_sem_mutar_entrada(self) -> None:
        entrada = [
            {"id": 10, "origem": "primeira", "itens": [{"produto_id": 1}]},
            {"id": 20, "origem": "unica", "itens": []},
            {"id": 10, "origem": "segunda", "itens": [{"produto_id": 2}]},
            {"id": 10, "origem": "terceira", "itens": []},
            {"id": 30, "origem": "ultima", "itens": []},
        ]
        copia_original = copy.deepcopy(entrada)

        unicos, descartados = desduplicar_pedidos(entrada)

        assert descartados == 2
        assert [p["id"] for p in unicos] == [10, 20, 30]
        assert unicos[0]["origem"] == "primeira"
        assert entrada == copia_original
        unicos[0]["itens"].append({"produto_id": 99})
        assert entrada == copia_original

    def test_lista_vazia_retorna_vazio_e_zero(self) -> None:
        assert desduplicar_pedidos([]) == ([], 0)

    @pytest.mark.parametrize(
        "entrada",
        [
            "nao_e_lista",
            [123],
            [{"cliente_id": 1}],
            [{"id": None}],
            [{"id": True}],
            [{"id": 0}],
            [{"id": -1}],
        ],
    )
    def test_pedidos_invalidos_lancam_value_error(self, entrada: object) -> None:
        with pytest.raises(ValueError):
            desduplicar_pedidos(entrada)  # type: ignore[arg-type]


class TestArmadilhaA6CalcularItensEDivergencia:
    def test_calcula_soma_linha_sequencial_e_sem_divergencia(self) -> None:
        itens_entrada = [
            {"produto_id": 1, "quantidade": 2, "preco_unitario": 3.5},
            {"produto_id": 3, "quantidade": 1, "preco_unitario": "8,90"},
        ]
        copia_original = copy.deepcopy(itens_entrada)

        itens_norm, valor_itens, divergente = calcular_itens_e_divergencia(
            itens_entrada, Decimal("15.90")
        )

        assert itens_norm == [
            {
                "linha": 1,
                "produto_id": 1,
                "quantidade": 2,
                "preco_unitario": Decimal("3.50"),
            },
            {
                "linha": 2,
                "produto_id": 3,
                "quantidade": 1,
                "preco_unitario": Decimal("8.90"),
            },
        ]
        assert valor_itens == Decimal("15.90")
        assert divergente is False
        assert itens_entrada == copia_original

    @pytest.mark.parametrize(
        ("valor_total", "esperado_divergente"),
        [
            (Decimal("10.00"), False),
            (Decimal("10.01"), False),
            (Decimal("9.99"), False),
            (Decimal("10.02"), True),
            (Decimal("9.98"), True),
        ],
    )
    def test_fronteira_tolerancia_um_centavo(
        self, valor_total: Decimal, esperado_divergente: bool
    ) -> None:
        itens = [{"produto_id": 1, "quantidade": 1, "preco_unitario": Decimal("10.00")}]
        _, valor_itens, divergente = calcular_itens_e_divergencia(itens, valor_total)
        assert valor_itens == Decimal("10.00")
        assert divergente is esperado_divergente

    def test_valor_total_negativo_sinaliza_divergencia(self) -> None:
        itens = [{"produto_id": 1, "quantidade": 1, "preco_unitario": 3.16}]
        _, valor_itens, divergente = calcular_itens_e_divergencia(itens, Decimal("-1.84"))
        assert valor_itens == Decimal("3.16")
        assert divergente is True

    def test_itens_vazios_e_preco_zero(self) -> None:
        assert calcular_itens_e_divergencia([], Decimal("0.00")) == (
            [],
            Decimal("0.00"),
            False,
        )
        assert calcular_itens_e_divergencia([], Decimal("5.00")) == (
            [],
            Decimal("0.00"),
            True,
        )
        itens_gratis, soma_gratis, div_gratis = calcular_itens_e_divergencia(
            [{"produto_id": 2, "quantidade": 2, "preco_unitario": Decimal("0.00")}],
            Decimal("0.00"),
        )
        assert itens_gratis[0]["preco_unitario"] == Decimal("0.00")
        assert soma_gratis == Decimal("0.00")
        assert div_gratis is False

    @pytest.mark.parametrize(
        ("itens", "valor_total"),
        [
            ([], 10.0),
            ([], True),
            ([], Decimal("NaN")),
            ("nao_lista", Decimal("10.00")),
            ([{"quantidade": 1, "preco_unitario": 1.0}], Decimal("1.00")),
            ([{"produto_id": True, "quantidade": 1, "preco_unitario": 1.0}], Decimal("1.00")),
            ([{"produto_id": 0, "quantidade": 1, "preco_unitario": 1.0}], Decimal("1.00")),
            ([{"produto_id": 1, "quantidade": 0, "preco_unitario": 1.0}], Decimal("1.00")),
            ([{"produto_id": 1, "quantidade": False, "preco_unitario": 1.0}], Decimal("1.00")),
            ([{"produto_id": 1, "quantidade": 1, "preco_unitario": -0.01}], Decimal("0.00")),
            ([{"produto_id": 1, "quantidade": 1, "preco_unitario": True}], Decimal("1.00")),
            ([{"produto_id": 1, "quantidade": 1, "preco_unitario": float("nan")}], Decimal("1.00")),
        ],
    )
    def test_entradas_invalidas_lancam_value_error(
        self, itens: object, valor_total: object
    ) -> None:
        with pytest.raises(ValueError):
            calcular_itens_e_divergencia(itens, valor_total)  # type: ignore[arg-type]


class TestOrquestradoresEmLote:
    def test_transformar_produtos_aceita_tipado_e_texto_bruto(self) -> None:
        brutos = [
            {
                "produto_id": 1,
                "nome": " Alface crespa ",
                "categoria": " folhas ",
                "preco_base": Decimal("3.50"),
            },
            {
                "produto_id": "2",
                "nome": "Rucula",
                "categoria": "folhas",
                "preco_base": "4,20",
            },
        ]
        copia = copy.deepcopy(brutos)

        limpos = transformar_produtos(brutos)

        assert limpos == [
            {
                "produto_id": 1,
                "nome": "Alface crespa",
                "categoria": "folhas",
                "preco_base": Decimal("3.50"),
            },
            {
                "produto_id": 2,
                "nome": "Rucula",
                "categoria": "folhas",
                "preco_base": Decimal("4.20"),
            },
        ]
        assert brutos == copia

    def test_transformar_produtos_rejeita_preco_nao_positivo_ou_campo_ausente(self) -> None:
        with pytest.raises(ErroTransformacao):
            transformar_produtos(
                [{"produto_id": 1, "nome": "Alface", "categoria": "folhas", "preco_base": 0}]
            )
        with pytest.raises(ErroTransformacao):
            transformar_produtos([{"produto_id": 1, "nome": "Alface"}])

    def test_transformar_clientes_contadores_e_imutabilidade(self) -> None:
        brutos = [
            {
                "id": 1,
                "nome": " João O'Reilly ",
                "email": None,
                "cidade": " São Paulo ",
                "estado": "sp",
                "cadastro_em": "2025-03-10",
            },
            {
                "id": 2,
                "nome": "Maria Silva",
                "email": "maria@exemplo.com",
                "cidade": "Curitiba",
                "estado": "PR",
                "cadastro_em": "2024-11-01",
            },
            {
                "id": 3,
                "nome": "Pedro Costa",
                "email": "   ",
                "cidade": "Rio de Janeiro",
                "estado": "rj",
                "cadastro_em": "2025-01-15",
            },
        ]
        copia = copy.deepcopy(brutos)

        clientes, contadores = transformar_clientes(brutos)

        assert contadores == {
            "total_clientes": 3,
            "emails_nulos": 2,
            "estados_padronizados": 2,
        }
        assert clientes[0] == {
            "id": 1,
            "nome": "João O'Reilly",
            "email": None,
            "cidade": "São Paulo",
            "estado": "SP",
            "cadastro_em": date(2025, 3, 10),
        }
        assert brutos == copia

    def test_transformar_pedidos_executa_a5_antes_de_a3_a4_e_a6(self) -> None:
        duplicado = {
            "id": 10,
            "cliente_id": 1,
            "data_pedido": "19/02/2026",
            "status": "entregue",
            "valor_total": "50,00",
            "itens": [
                {"produto_id": 1, "quantidade": 2, "preco_unitario": 10.0},
                {"produto_id": 2, "quantidade": 1, "preco_unitario": 20.0},
            ],
        }
        brutos = [
            copy.deepcopy(duplicado),
            {
                "id": 20,
                "cliente_id": 2,
                "data_pedido": "2026-02-20",
                "status": "cancelado",
                "valor_total": 15.0,
                "itens": [{"produto_id": 3, "quantidade": 1, "preco_unitario": 15.0}],
            },
            copy.deepcopy(duplicado),
        ]
        copia = copy.deepcopy(brutos)

        pedidos, itens, contadores = transformar_pedidos(brutos)

        assert contadores == {
            "pedidos_brutos": 3,
            "pedidos_unicos": 2,
            "repetidos_descartados": 1,
            "datas_convertidas": 1,
            "valores_convertidos": 1,
            "divergentes": 1,
            "total_itens": 3,
        }
        assert pedidos == [
            {
                "id": 10,
                "cliente_id": 1,
                "data_pedido": date(2026, 2, 19),
                "status": "entregue",
                "valor_total": Decimal("50.00"),
                "valor_itens": Decimal("40.00"),
                "divergente": True,
            },
            {
                "id": 20,
                "cliente_id": 2,
                "data_pedido": date(2026, 2, 20),
                "status": "cancelado",
                "valor_total": Decimal("15.00"),
                "valor_itens": Decimal("15.00"),
                "divergente": False,
            },
        ]
        assert itens == [
            {
                "pedido_id": 10,
                "linha": 1,
                "produto_id": 1,
                "quantidade": 2,
                "preco_unitario": Decimal("10.00"),
            },
            {
                "pedido_id": 10,
                "linha": 2,
                "produto_id": 2,
                "quantidade": 1,
                "preco_unitario": Decimal("20.00"),
            },
            {
                "pedido_id": 20,
                "linha": 1,
                "produto_id": 3,
                "quantidade": 1,
                "preco_unitario": Decimal("15.00"),
            },
        ]
        assert brutos == copia

    def test_seed_2026_insumos_contadores_e_soma_exatos(self) -> None:
        produtos = transformar_produtos(ler_produtos_csv(INSUMOS_DADOS / "produtos.csv"))
        with (INSUMOS_DADOS / "clientes.json").open("r", encoding="utf-8") as arq_cli:
            clientes_brutos = json.load(arq_cli)
        with (INSUMOS_DADOS / "pedidos.json").open("r", encoding="utf-8") as arq_ped:
            pedidos_brutos = json.load(arq_ped)

        clientes, cont_cli = transformar_clientes(clientes_brutos)
        pedidos, itens, cont_ped = transformar_pedidos(pedidos_brutos)

        assert len(produtos) == 12
        assert len(clientes) == 1000
        assert cont_cli == {
            "total_clientes": 1000,
            "emails_nulos": 81,
            "estados_padronizados": 151,
        }
        assert cont_ped == {
            "pedidos_brutos": 5100,
            "pedidos_unicos": 5000,
            "repetidos_descartados": 100,
            "datas_convertidas": 1037,
            "valores_convertidos": 1255,
            "divergentes": 238,
            "total_itens": 12455,
        }
        assert len(itens) == 12455
        assert sum((p["valor_itens"] for p in pedidos), Decimal("0.00")) == Decimal("311228.75")

        pedido_81 = next(p for p in pedidos if p["id"] == 81)
        assert pedido_81["valor_total"] == Decimal("-1.84")
        assert pedido_81["valor_itens"] == Decimal("3.16")
        assert pedido_81["divergente"] is True
