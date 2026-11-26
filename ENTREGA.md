# Entrega — Desafio Final ETL Verdejar

1. **Link do Pull Request:** `PREENCHER_APOS_O_PUSH` (branch `desafio-final-cca`)
2. **Link público do vídeo:** `PREENCHER_APOS_A_GRAVACAO`

## 3. Como usei IA

(Cópia de [COMO_USEI_IA.md](COMO_USEI_IA.md).)

### Sugestões aceitas
1. **Funções puras A1–A6 com `Decimal`.** Dinheiro em `float` acumula erro e a reconciliação exige `diferenca=0.00`. Validação: 107 testes `pytest` passando, incluindo a conferência exata da seed 2026.
2. **Carga com `ON CONFLICT DO UPDATE` em uma transação.** Evita duplicar linhas e não deixa meia carga. Validação: duas execuções seguidas deram contagens idênticas.

### Sugestões rejeitadas
1. **Porta 5432 para o PostgreSQL.** Estava ocupada na minha máquina. Entrou `-p 5434:5432` com `PGPORT=5434` no `.env`. Validação: `docker ps` e ETL conectando.
2. **Contar os 5000 pedidos em `datas_convertidas` e `valores_convertidos`.** O contador deve mostrar quantos tinham o problema. Entrou 1037 e 1255, conferidos no `pedidos.json`.

### Falha e retrabalho
A primeira extração aceitava timeout zero ou negativo, preço não finito ou não positivo e colunas extras no CSV. A revisão achou os casos. Corrigi no commit `88057e8` e os testes de borda passam.

## 4. Reflexão

Usei a IA para ganhar velocidade na parte repetitiva: extração paginada, funções de transformação e testes. Mas nenhuma sugestão entrou sem conferência contra o esquema, os dados da seed 2026 ou um teste. O que mais pesou foi dinheiro com `Decimal` e contadores com um critério claro, pois eles decidem se a reconciliação fecha em `0.00`.

Aprendi que "o código roda" não prova que o dado está certo. A reconciliação (311228.75 na origem e no destino) e a prova de que a soma dos meses bate com o total geral dão confiança que a execução sozinha não dá. A idempotência também só foi aceita depois de rodar o ETL duas vezes e comparar as saídas.

Os limites da IA apareceram em detalhes do meu ambiente, como as portas 5432 e 5433 já ocupadas. Também apareceram em decisões de critério: contar 5000 ou 1037 conversões parecia indiferente para o parser, mas muda o que o relatório diz. A primeira extração falhava com entradas inválidas que só uma revisão adversarial achou.

Se fosse refazer, escreveria os testes de borda da extração antes do código. Na próxima vez, peço à IA que justifique cada decisão de contador e de tolerância antes de aceitar. Fico com a regra de não confiar em código que eu não consiga explicar linha a linha.
