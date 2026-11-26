# Contrato de Dados — ETL Verdejar (Caminho B · PostgreSQL)

Este documento define o contrato formal entre os dados brutos extraidos da API local da Verdejar (`/clientes`, `/pedidos`) e do catalogo CSV (`produtos.csv`) e o esquema relacional de destino em PostgreSQL (`insumos/schema.sql`).

## 1. Visao Geral e Ordem de Carga

- **Banco de destino:** PostgreSQL 16 (`verdejar`), esquema definido em `insumos/schema.sql` (4 tabelas, 22 colunas no total).
- **Ordem obrigatoria de carga (integridade referencial / FKs):**
  1. `produtos`
  2. `clientes`
  3. `pedidos` (depende de `clientes(id)`)
  4. `itens_pedido` (depende de `pedidos(id)` e `produtos(produto_id)`)
- **Politica de validacao na transformacao:** As funcoes de `etl/transformacao.py` sao puras (sem E/S e sem mutacao das estruturas de entrada) e rejeitam explicitamente registros invalidos (`ValueError` / `ErroTransformacao`), incluindo booleanos no lugar de inteiros/numeros, valores `NaN`/`Infinity`, datas inexistentes, formatos monetarios ambiguos (ex.: `"1.234,56"`) e campos obrigatorios ausentes.
- **Reconciliacao pos-carga:** Compara a contagem de pedidos unicos (`5000` na Seed 2026) e a soma de `valor_itens` (`311228.75` na Seed 2026) entre os dados transformados na origem e a tabela `pedidos` no PostgreSQL, com tolerancia maxima de `0.01` (esperado `diferenca = 0.00`).

---

## 2. Tabela `clientes`

Origem: endpoint paginado `GET /clientes` (preservado em `brutos/clientes.json`).  
Chave primaria: `PRIMARY KEY (id)`.

| Campo | Tipo PostgreSQL | Nulabilidade / Restricoes | Origem | Regra de Transformacao |
|---|---|---|---|---|
| `id` | `INTEGER` | `NOT NULL`, `PRIMARY KEY` | `clientes[].id` | Validar inteiro estritamente positivo (`> 0`, nao `bool`). |
| `nome` | `TEXT` | `NOT NULL` | `clientes[].nome` | Remover espacos nas extremidades (`strip()`); validar texto nao vazio. |
| `email` | `TEXT` | `NULL` (anulavel) | `clientes[].email` | **Armadilha A1:** Manter o registro do cliente. Se `None` ou texto vazio/apenas espacos, gravar `NULL` (`None`) e incrementar `emails_nulos`. Caso contrario, aplicar `strip()`. |
| `cidade` | `TEXT` | `NOT NULL` | `clientes[].cidade` | Remover espacos nas extremidades (`strip()`); validar texto nao vazio. |
| `estado` | `CHAR(2)` | `NOT NULL` | `clientes[].estado` | **Armadilha A2:** Remover espacos, validar exatamente 2 letras ASCII alfabeticas (`[A-Za-z]{2}`) e converter para maiusculas (`[A-Z]{2}`). Incrementar `estados_padronizados` quando o valor bruto diferir do normalizado. |
| `cadastro_em` | `DATE` | `NOT NULL` | `clientes[].cadastro_em` | Converter data de entrada (`YYYY-MM-DD` ou `DD/MM/YYYY`) para `datetime.date` (`DATE` no PostgreSQL), **sem** incrementar o contador `datas_convertidas` (reservado a A3 em `pedidos.data_pedido`). |

---

## 3. Tabela `produtos`

Origem: arquivo CSV UTF-8 `insumos/dados/produtos.csv`.  
Chave primaria: `PRIMARY KEY (produto_id)`.

| Campo | Tipo PostgreSQL | Nulabilidade / Restricoes | Origem | Regra de Transformacao |
|---|---|---|---|---|
| `produto_id` | `INTEGER` | `NOT NULL`, `PRIMARY KEY` | `produtos.csv -> produto_id` | Validar inteiro estritamente positivo (`> 0`, nao `bool`; aceita inteiro ja convertido ou texto numerico inteiro). |
| `nome` | `TEXT` | `NOT NULL` | `produtos.csv -> nome` | Remover espacos nas extremidades (`strip()`); validar texto nao vazio. |
| `categoria` | `TEXT` | `NOT NULL` | `produtos.csv -> categoria` | Remover espacos nas extremidades (`strip()`); validar texto nao vazio. |
| `preco_base` | `NUMERIC(10,2)` | `NOT NULL` | `produtos.csv -> preco_base` | Converter para `Decimal` finito estritamente positivo (`> 0.00`), quantizado em 2 casas decimais (`ROUND_HALF_UP`). |

---

## 4. Tabela `pedidos`

Origem: endpoint paginado `GET /pedidos` (preservado em `brutos/pedidos.json`).  
Chave primaria: `PRIMARY KEY (id)`.  
Chave estrangeira: `FOREIGN KEY (cliente_id) REFERENCES clientes(id)`.

| Campo | Tipo PostgreSQL | Nulabilidade / Restricoes | Origem | Regra de Transformacao |
|---|---|---|---|---|
| `id` | `INTEGER` | `NOT NULL`, `PRIMARY KEY` | `pedidos[].id` | **Armadilha A5:** Executar desduplicacao **antes** das transformacoes A3, A4 e A6. Manter a primeira ocorrencia de cada `id` positivo preservando a ordem; contabilizar `pedidos_unicos` e `repetidos_descartados`. |
| `cliente_id` | `INTEGER` | `NOT NULL`, `REFERENCES clientes(id)` | `pedidos[].cliente_id` | Validar inteiro estritamente positivo (`> 0`, nao `bool`) referenciando cliente valido. |
| `data_pedido` | `DATE` | `NOT NULL` | `pedidos[].data_pedido` | **Armadilha A3:** Converter datas validas nos formatos `YYYY-MM-DD` e `DD/MM/YYYY` para `datetime.date` (`DATE`). Incrementar `datas_convertidas` apenas quando o pedido unico estiver em `DD/MM/YYYY`. |
| `status` | `TEXT` | `NOT NULL` | `pedidos[].status` | Remover espacos nas extremidades (`strip()`); validar texto nao vazio (ex.: `entregue`, `cancelado`, `em_transporte`). |
| `valor_total` | `NUMERIC(12,2)` | `NOT NULL` | `pedidos[].valor_total` | **Armadilha A4 (e impacto A6):** Converter numero (`int`, `float`, `Decimal`) ou texto com virgula decimal (ex.: `"125,84"`) para `Decimal` quantizado em 2 casas (`ROUND_HALF_UP`), incrementando `valores_convertidos` quando houver virgula decimal. **Valores negativos finitos sao permitidos**, pois a armadilha A6 pode subtrair `5.00` em pedidos pequenos (ex.: pedido `id=81` na Seed 2026 com `valor_total = -1.84`). |
| `valor_itens` | `NUMERIC(12,2)` | `NOT NULL` | Derivado de `pedidos[].itens` | **Armadilha A6:** Calcular `SUM(quantidade * preco_unitario)` sobre os itens do pedido em `Decimal`, quantizado em 2 casas (`ROUND_HALF_UP`). |
| `divergente` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Derivado de `valor_total` e `valor_itens` | **Armadilha A6:** Definir `TRUE` quando `abs(valor_total - valor_itens) > 0.01` (diferenca estritamente maior que 1 centavo) e `FALSE` quando `<= 0.01`. Contabilizar no contador `divergentes`. |

---

## 5. Tabela `itens_pedido`

Origem: lista aninhada `itens` de cada pedido unico em `GET /pedidos` (apos **A5**).  
Chave primaria composta: `PRIMARY KEY (pedido_id, linha)`.  
Chaves estrangeiras: `FOREIGN KEY (pedido_id) REFERENCES pedidos(id)` e `FOREIGN KEY (produto_id) REFERENCES produtos(produto_id)`.

| Campo | Tipo PostgreSQL | Nulabilidade / Restricoes | Origem | Regra de Transformacao |
|---|---|---|---|---|
| `pedido_id` | `INTEGER` | `NOT NULL`, `PRIMARY KEY (pedido_id, linha)`, `REFERENCES pedidos(id)` | `pedidos[].id` | Herdado do registro unico do pedido apos desduplicacao (A5). |
| `linha` | `INTEGER` | `NOT NULL`, `PRIMARY KEY (pedido_id, linha)` | Gerado na transformacao | Numero sequencial 1-based (`1, 2, ..., N`) por pedido, preservando a ordem original da lista `itens`. |
| `produto_id` | `INTEGER` | `NOT NULL`, `REFERENCES produtos(produto_id)` | `pedidos[].itens[].produto_id` | Validar inteiro estritamente positivo (`> 0`, nao `bool`) referenciando produto valido. |
| `quantidade` | `INTEGER` | `NOT NULL` | `pedidos[].itens[].quantidade` | Validar inteiro estritamente positivo (`> 0`, nao `bool`). |
| `preco_unitario` | `NUMERIC(10,2)` | `NOT NULL` | `pedidos[].itens[].preco_unitario` | Converter para `Decimal` finito nao negativo (`>= 0.00`) quantizado em 2 casas decimais (`ROUND_HALF_UP`). |

---

## 6. Referencia de Contadores (Seed Oficial `2026`)

Na base deterministica oficial (`insumos/dados/` e `brutos/`):

- `produtos`: `12`
- `total_clientes`: `1000` (`emails_nulos = 81`, `estados_padronizados = 151`)
- `pedidos_brutos`: `5100`
- `pedidos_unicos`: `5000` (`repetidos_descartados = 100`)
- `datas_convertidas`: `1037` (A3 contabilizada apos A5)
- `valores_convertidos`: `1255` (A4 contabilizada apos A5)
- `divergentes`: `238` (A6 contabilizada apos A5)
- `total_itens`: `12455` (`SUM(valor_itens) = 311228.75`)
