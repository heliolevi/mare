# Arquivos reais de bancos (anonimizados)

Cada arquivo aqui é uma fatura ou extrato real, **já anonimizado**, que vira um teste automático (`tests/test_bancos.py`). Se um banco mudar o formato de exportação, ou um ajuste na leitura quebrar um banco que funcionava, o teste daquele banco falha com o nome dele.

**Este repositório é público.** Nunca coloque aqui um arquivo cru.

## Como adicionar um banco

1. Exporte o arquivo no app ou no site do banco (OFX de preferência; CSV também serve).
2. Guarde o **original** em `tests/bancos/_originais/` (essa pasta é ignorada pelo git) ou fora do projeto.
3. Anonimize:

   ```powershell
   .venv\Scripts\python tools\anonimizar.py tests\bancos\_originais\ORIGINAL.ofx tests\bancos\nubank-conta.ofx --generico
   ```

   O nome de saída precisa ser neutro (sem número de conta). O script recusa se achar dado pessoal sobrando e não imprime o conteúdo original.

   Use sempre `--generico` num repositório público: sem ele só saem CPF, CNPJ, agência, conta e nomes de pessoas, mas o nome das lojas continua, e isso entrega a cidade da pessoa, a cooperativa do banco e até a religião (uma doação a uma igreja, por exemplo). Com `--generico`, cada loja ou empresa vira um nome genérico da mesma categoria (`RESTAURANTE EXEMPLO 01`), e os bancos pequenos viram `BANCO EXEMPLO`. Marcas conhecidas (Netflix, Mercado Livre) e os grandes bancos ficam. Datas e valores nunca mudam.
4. Leia a lista "Confira se sobrou algum nome" que o script mostra e abra o arquivo gerado: procure nomes, apelidos e números que ainda façam sentido para alguém. O script só acha o que tem formato conhecido (CPF, CNPJ, agência, conta, e-mail, telefone, e o nome de pessoa que vem antes de um CPF).
5. Crie ao lado o arquivo com o resultado esperado, com o mesmo nome e a extensão `.esperado.json`:

   ```json
   {"banco": "Nubank", "formato": "ofx", "conta": true, "status": "sem_total", "linhas": 40}
   ```

   - `conta`: `true` para extrato de conta, `false` para fatura de cartão.
   - `status`: `"ok"` se o arquivo traz o total e a soma bate ("Conferido"); `"sem_total"` para extratos de conta.
   - `total_cents` (opcional): o total da fatura em centavos, para conferir também o valor.
6. Rode `.venv\Scripts\python -m pytest tests\test_bancos.py -v`.

## Convenção de nomes

`banco-tipo.extensão`, por exemplo `nubank-conta.ofx`, `nubank-cartao.csv`, `bb-cartao.ofx`. Arquivos sintéticos (inventados, não exportados de um banco de verdade) levam `sintetico` no nome, para ninguém achar que provam o formato real do banco.
