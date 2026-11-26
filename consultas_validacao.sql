-- Consultas de validacao pos-carga do Desafio Final ETL Verdejar (PostgreSQL).

-- (a) Total de vendas por mes usando valor_itens (valor reconciliado dos itens)
SELECT
    TO_CHAR(DATE_TRUNC('month', data_pedido), 'YYYY-MM') AS mes,
    COUNT(*) AS quantidade_pedidos,
    SUM(valor_itens)::NUMERIC(12,2) AS total_vendas
FROM pedidos
GROUP BY DATE_TRUNC('month', data_pedido)
ORDER BY DATE_TRUNC('month', data_pedido);

-- (a-teste) Teste de consulta: prova que a soma dos meses bate com a soma geral da tabela
WITH vendas_mensais AS (
    SELECT
        DATE_TRUNC('month', data_pedido) AS mes,
        SUM(valor_itens) AS total_mes
    FROM pedidos
    GROUP BY DATE_TRUNC('month', data_pedido)
),
total_geral AS (
    SELECT COALESCE(SUM(valor_itens), 0.00)::NUMERIC(12,2) AS soma_geral
    FROM pedidos
)
SELECT
    COALESCE((SELECT SUM(total_mes) FROM vendas_mensais), 0.00)::NUMERIC(12,2) AS soma_dos_meses,
    tg.soma_geral AS soma_geral_tabela,
    ABS(
        COALESCE((SELECT SUM(total_mes) FROM vendas_mensais), 0.00) - tg.soma_geral
    )::NUMERIC(12,2) AS diferenca
FROM total_geral tg;

-- (b) Quantidade de pedidos por estado do cliente
SELECT
    c.estado,
    COUNT(*) AS quantidade_pedidos
FROM pedidos p
JOIN clientes c ON c.id = p.cliente_id
GROUP BY c.estado
ORDER BY c.estado;

-- (c) Pedidos divergentes (valor_total diferente da soma dos itens acima da tolerancia)
SELECT
    id,
    cliente_id,
    data_pedido,
    status,
    valor_total,
    valor_itens,
    (valor_total - valor_itens)::NUMERIC(12,2) AS diferenca
FROM pedidos
WHERE divergente = TRUE
ORDER BY id;
