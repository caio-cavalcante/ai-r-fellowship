# ETL Verdejar — Desafio Final (Caminho B: PostgreSQL em Docker)

Pipeline que extrai clientes e pedidos da API local da Verdejar, lê `produtos.csv`, trata as 6 armadilhas (A1–A6), carrega no PostgreSQL 16 e reconcilia os totais.

**Bibliotecas:** `requests`/`urllib` para a API, `psycopg2` para o PostgreSQL, `python-dotenv` para o `.env`, `pytest` para os testes (ver `requirements.txt`).

## Como rodar

```powershell
# 1. Ambiente
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # ajuste PGPASSWORD (o .env nao e versionado)

# 2. PostgreSQL 16 em Docker (porta 5434 no host, pois 5432 e 5433 estavam ocupadas)
docker run --name verdejar-pg -e POSTGRES_PASSWORD=$env:PGPASSWORD -e POSTGRES_DB=verdejar -p 5434:5432 -d postgres:16
Get-Content insumos/schema.sql | docker exec -i verdejar-pg psql -U postgres -d verdejar

# 3. API local (deixe rodando em outro terminal)
python insumos/api_verdejar.py
curl http://127.0.0.1:8000/saude

# 4. ETL e testes
.\.venv\Scripts\python.exe -m etl.main
.\.venv\Scripts\python.exe -m pytest tests -v

# 5. Consultas de validacao
Get-Content consultas_validacao.sql | docker exec -i verdejar-pg psql -U postgres -d verdejar
```

Estrutura: `etl/extracao.py` (D1), `etl/transformacao.py` (D2), `etl/carga.py` e `etl/main.py` (D3), `tests/`, `consultas_validacao.sql`, `CONTRATO_DE_DADOS.md`.

## Idempotência

A carga roda em **uma transação** e usa `INSERT ... ON CONFLICT (...) DO UPDATE` com queries parametrizadas (`%s`), na ordem `produtos -> clientes -> pedidos -> itens_pedido`. Os itens dos pedidos recarregados são apagados e reinseridos dentro da mesma transação. Rodar o ETL de novo regrava as mesmas linhas, sem duplicar. As duas execuções abaixo mostram saída idêntica.

## Saída do ETL — execução 1

```text
extracao: clientes paginas=20 registros=1000
extracao: pedidos paginas=102 registros_brutos=5100
transformacao: pedidos_unicos=5000 repetidos_descartados=100
transformacao: emails_nulos=81 estados_padronizados=151 datas_convertidas=1037 valores_convertidos=1255
carga: clientes=1000 produtos=12 pedidos=5000 itens=12455
reconciliacao: soma_valor_itens_origem=311228.75 soma_valor_itens_destino=311228.75 diferenca=0.00
divergentes: 238 pedidos com valor_total diferente da soma dos itens
```

## Saída do ETL — execução 2 (idêntica)

```text
extracao: clientes paginas=20 registros=1000
extracao: pedidos paginas=102 registros_brutos=5100
transformacao: pedidos_unicos=5000 repetidos_descartados=100
transformacao: emails_nulos=81 estados_padronizados=151 datas_convertidas=1037 valores_convertidos=1255
carga: clientes=1000 produtos=12 pedidos=5000 itens=12455
reconciliacao: soma_valor_itens_origem=311228.75 soma_valor_itens_destino=311228.75 diferenca=0.00
divergentes: 238 pedidos com valor_total diferente da soma dos itens
```

Os contadores `datas_convertidas` e `valores_convertidos` contam só os registros que de fato precisaram de conversão (data em `DD/MM/AAAA`, valor com vírgula), no mesmo critério de `emails_nulos` e `estados_padronizados`.

## Consultas de validação (`consultas_validacao.sql`)

**(a) Total de vendas por mês** (soma de `valor_itens`):

```text
   mes   | quantidade_pedidos | total_vendas
---------+--------------------+--------------
 2026-01 |                488 |     30355.02
 2026-02 |                536 |     33855.86
 2026-03 |                487 |     30617.70
 2026-04 |                521 |     31170.96
 2026-05 |                512 |     30777.02
 2026-06 |                523 |     31557.73
 2026-07 |                519 |     32685.17
 2026-08 |                458 |     29260.04
 2026-09 |                476 |     29909.71
 2026-10 |                480 |     31039.54
(10 rows)
```

**Teste de consulta** (a soma dos meses bate com a soma geral da tabela):

```text
 soma_dos_meses | soma_geral_tabela | diferenca
----------------+-------------------+-----------
      311228.75 |         311228.75 |      0.00
```

**(b) Pedidos por estado:**

```text
 estado | quantidade_pedidos
--------+--------------------
 MG     |                476
 PR     |                974
 RS     |               1543
 SC     |               1127
 SP     |                880
(5 rows)
```

**(c) Pedidos divergentes** (`WHERE divergente = TRUE`): 238 linhas, o mesmo número que o ETL reportou. As cinco primeiras:

```text
  id  | cliente_id | data_pedido |    status     | valor_total | valor_itens | diferenca
------+------------+-------------+---------------+-------------+-------------+-----------
    1 |        303 | 2026-02-19  | entregue      |      125.84 |      130.84 |     -5.00
   51 |         23 | 2026-04-27  | cancelado     |       26.58 |       23.58 |      3.00
   71 |        962 | 2026-05-27  | cancelado     |      144.35 |      134.35 |     10.00
   81 |        198 | 2026-09-05  | entregue      |       -1.84 |        3.16 |     -5.00
  106 |        973 | 2026-05-02  | em_transporte |       47.78 |       44.78 |      3.00
(238 rows)
```

## Testes (`pytest`)

`tests/test_transformacao.py` cobre A1 a A6 (pelo menos um teste por armadilha, mais casos de borda e a conferência exata da seed 2026). `tests/test_reconciliacao.py` confere, depois da carga, a contagem de pedidos únicos e a soma de `valor_itens` com tolerância de 0,01.

Saída final:

```text
============================= 107 passed in 1.70s =============================
```

## Documentos

- `CONTRATO_DE_DADOS.md`: campos, tipos, nulabilidade e regras das 4 tabelas.
- `COMO_USEI_IA.md`: uso de IA (sugestões aceitas, rejeitadas e falhas).
- `ENTREGA.md`: links do PR e do vídeo, cópia do `COMO_USEI_IA.md` e reflexão.
