# Como usei IA

Usei agentes de IA como assistentes de programação, e eu decidi o que entrava. Cada sugestão foi conferida contra o esquema, os dados da seed 2026 ou os testes.

## Sugestões aceitas

### 1. Funções puras A1–A6 com `Decimal`
- **Trecho pedido:** "Implemente cada armadilha como função pequena e pura em `etl/transformacao.py`."
- **O que a IA propôs:** funções como `converter_valor` e `calcular_itens_e_divergencia`, que usam `Decimal` com `ROUND_HALF_UP`, e não `float`, e devolvem o valor junto com um booleano que alimenta o contador.
- **Por que aceitei:** dinheiro em `float` acumula erro, e a reconciliação exige `diferenca=0.00`. A função pura também é fácil de testar com `assert`.
- **Validação:** `pytest` com 107 testes passando, incluindo a conferência exata da seed 2026, e a reconciliação com `diferenca=0.00` no PostgreSQL.

### 2. Carga com `ON CONFLICT DO UPDATE` numa transação
- **Trecho pedido:** "Faça a carga idempotente com queries parametrizadas, na ordem das chaves estrangeiras."
- **O que a IA propôs:** `INSERT ... ON CONFLICT (...) DO UPDATE` com `%s`, em uma transação, e `DELETE` dos itens do pedido antes de reinseri-los.
- **Por que aceitei:** evita duplicar linhas se o ETL rodar de novo, e a transação não deixa meia carga se algo falhar.
- **Validação:** duas execuções seguidas do ETL deram contagens idênticas (1000 clientes, 12 produtos, 5000 pedidos, 12455 itens).

## Sugestões rejeitadas

### 1. Subir o PostgreSQL na porta 5432
- **Trecho pedido:** o comando `docker run ... -p 5432:5432` do runbook.
- **O que a IA propôs:** usar a porta padrão.
- **Por que rejeitei:** as portas 5432 e 5433 já estavam ocupadas por outros bancos da minha máquina. Usar a mesma porta quebraria os outros projetos ou falharia na subida.
- **O que entrou no lugar:** `-p 5434:5432` com `PGPORT=5434` no `.env`, documentado no `.env.example` e no `README.md`.
- **Validação:** `docker ps` mostra o `verdejar-pg` em 5434, e o ETL conecta e carrega sem erro.

### 2. Contar todos os 5000 pedidos em `datas_convertidas` e `valores_convertidos`
- **Trecho pedido:** o contador de A3 e A4.
- **O que a IA propôs:** contar todos os registros que passaram pelo parser, ou seja, 5000.
- **Por que rejeitei:** o contador deve dizer quantos registros tinham o problema, como `emails_nulos=81` e `estados_padronizados=151`. Contar tudo esconderia o tamanho real das armadilhas.
- **O que entrou no lugar:** só os efetivamente convertidos, `datas_convertidas=1037` (datas em `DD/MM/AAAA`) e `valores_convertidos=1255` (valores com vírgula).
- **Validação:** conferi esses números com a contagem direta em `insumos/dados/pedidos.json`, e o teste da seed 2026 também os verifica.

## Falhas e retrabalho

### Validações faltando na extração
- **Trecho pedido:** o módulo de extração (`etl/extracao.py`) da API paginada e do CSV.
- **O que falhou:** a primeira versão, aprovada de início, aceitava valores que quebram o ETL mais adiante, como timeout zero ou negativo, preço não finito ou não positivo e colunas extras no `produtos.csv`. A revisão adversarial achou os casos.
- **Retrabalho:** validação de timeout positivo, de preço finito e positivo e de colunas extras, no commit `88057e8` (`fix(extracao): valida timeout positivo, preco finito/positivo e colunas extras no CSV`).
- **Validação:** os testes de casos de borda passam, e uma nova revisão não encontrou mais problemas.
