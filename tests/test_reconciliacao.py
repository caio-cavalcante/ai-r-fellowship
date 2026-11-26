"""Testes unitarios e de integracao para carga e reconciliacao pos-carga."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
import pytest

from etl.carga import ErroCarga, conectar_banco, reconciliar_carga
from etl.transformacao import transformar_pedidos

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
INSUMOS_PEDIDOS_JSON = RAIZ_PROJETO / "insumos" / "dados" / "pedidos.json"


class _FakeCursor:
    def __init__(self, row: tuple[Any, Any]) -> None:
        self._row = row
        self.ultima_query: str | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def execute(self, query: str, params: Any = None) -> None:
        self.ultima_query = query

    def fetchone(self) -> tuple[Any, Any]:
        return self._row


class _FakeConn:
    def __init__(self, row: tuple[Any, Any]) -> None:
        self._cursor = _FakeCursor(row)

    def cursor(self) -> _FakeCursor:
        return self._cursor


class TestReconciliacaoOffline:
    def test_reconciliacao_exata_retorna_diferenca_zero(self) -> None:
        pedidos = [
            {"id": 1, "valor_itens": Decimal("10.50")},
            {"id": 2, "valor_itens": Decimal("25.25")},
        ]
        conn = _FakeConn((2, Decimal("35.75")))

        resultado = reconciliar_carga(conn, pedidos)

        assert resultado == {
            "pedidos_origem": 2,
            "pedidos_destino": 2,
            "soma_valor_itens_origem": Decimal("35.75"),
            "soma_valor_itens_destino": Decimal("35.75"),
            "diferenca": Decimal("0.00"),
        }

    @pytest.mark.parametrize("soma_destino", [Decimal("35.76"), Decimal("35.74")])
    def test_reconciliacao_aceita_fronteira_um_centavo(
        self, soma_destino: Decimal
    ) -> None:
        pedidos = [
            {"id": 1, "valor_itens": Decimal("10.50")},
            {"id": 2, "valor_itens": Decimal("25.25")},
        ]
        conn = _FakeConn((2, soma_destino))

        resultado = reconciliar_carga(conn, pedidos)

        assert resultado["diferenca"] == Decimal("0.01")

    @pytest.mark.parametrize("soma_destino", [Decimal("35.77"), Decimal("35.73")])
    def test_reconciliacao_rejeita_acima_da_tolerancia(
        self, soma_destino: Decimal
    ) -> None:
        pedidos = [
            {"id": 1, "valor_itens": Decimal("10.50")},
            {"id": 2, "valor_itens": Decimal("25.25")},
        ]
        conn = _FakeConn((2, soma_destino))

        with pytest.raises(ErroCarga, match="valor_itens"):
            reconciliar_carga(conn, pedidos)

    def test_reconciliacao_rejeita_contagem_divergente(self) -> None:
        pedidos = [{"id": 1, "valor_itens": Decimal("10.00")}]
        conn = _FakeConn((2, Decimal("10.00")))

        with pytest.raises(ErroCarga, match="contagem"):
            reconciliar_carga(conn, pedidos)

    def test_reconciliacao_lista_vazia_com_destino_vazio(self) -> None:
        conn = _FakeConn((0, 0))

        resultado = reconciliar_carga(conn, [])

        assert resultado == {
            "pedidos_origem": 0,
            "pedidos_destino": 0,
            "soma_valor_itens_origem": Decimal("0.00"),
            "soma_valor_itens_destino": Decimal("0.00"),
            "diferenca": Decimal("0.00"),
        }


class TestConectarBancoOffline:
    def test_variavel_ausente_lanca_erro_carga(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        for var in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"):
            monkeypatch.delenv(var, raising=False)
        env_vazio = tmp_path / ".env"
        env_vazio.write_text("", encoding="utf-8")

        with pytest.raises(ErroCarga, match="PGHOST"):
            conectar_banco(env_path=env_vazio)

    def test_porta_invalida_lanca_erro_carga(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("PGHOST", "127.0.0.1")
        monkeypatch.setenv("PGPORT", "nao_inteiro")
        monkeypatch.setenv("PGDATABASE", "verdejar")
        monkeypatch.setenv("PGUSER", "postgres")
        monkeypatch.setenv("PGPASSWORD", "segredo_super_confidencial")
        env_vazio = tmp_path / ".env"
        env_vazio.write_text("", encoding="utf-8")

        with pytest.raises(ErroCarga, match="PGPORT") as exc_info:
            conectar_banco(env_path=env_vazio)
        assert "segredo_super_confidencial" not in str(exc_info.value)

    def test_erro_psycopg2_nao_expoe_senha(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("PGHOST", "127.0.0.1")
        monkeypatch.setenv("PGPORT", "5434")
        monkeypatch.setenv("PGDATABASE", "verdejar")
        monkeypatch.setenv("PGUSER", "postgres")
        monkeypatch.setenv("PGPASSWORD", "segredo_super_confidencial")
        env_vazio = tmp_path / ".env"
        env_vazio.write_text("", encoding="utf-8")

        def _falhar_connect(**kwargs: Any) -> Any:
            raise psycopg2.OperationalError(
                "authentication failed for user postgres with password segredo_super_confidencial"
            )

        monkeypatch.setattr(psycopg2, "connect", _falhar_connect)

        with pytest.raises(ErroCarga) as exc_info:
            conectar_banco(env_path=env_vazio)
        assert "segredo_super_confidencial" not in str(exc_info.value)


class TestReconciliacaoBancoPosCarga:
    def test_contagens_tabelas_pos_carga(self) -> None:
        conn = conectar_banco()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM produtos")
                total_produtos = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM clientes")
                total_clientes = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM pedidos")
                total_pedidos = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM itens_pedido")
                total_itens = int(cur.fetchone()[0])
        finally:
            conn.close()

        assert total_produtos == 12
        assert total_clientes == 1000
        assert total_pedidos == 5000
        assert total_itens == 12455

    def test_reconciliacao_banco_contra_pedidos_seed_2026(self) -> None:
        with INSUMOS_PEDIDOS_JSON.open("r", encoding="utf-8") as arq:
            pedidos_brutos = json.load(arq)
        pedidos_unicos, _, contadores = transformar_pedidos(pedidos_brutos)

        conn = conectar_banco()
        try:
            resultado = reconciliar_carga(conn, pedidos_unicos)
        finally:
            conn.close()

        assert contadores["pedidos_unicos"] == 5000
        assert resultado["pedidos_origem"] == 5000
        assert resultado["pedidos_destino"] == 5000
        assert resultado["soma_valor_itens_origem"] == Decimal("311228.75")
        assert resultado["soma_valor_itens_destino"] == Decimal("311228.75")
        assert resultado["diferenca"] <= Decimal("0.01")
        assert resultado["diferenca"] == Decimal("0.00")

    def test_contagem_pedidos_divergentes_banco(self) -> None:
        conn = conectar_banco()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM pedidos WHERE divergente = TRUE")
                divergentes = int(cur.fetchone()[0])
        finally:
            conn.close()

        assert divergentes == 238
