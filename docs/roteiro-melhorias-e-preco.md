# Maré: fases práticas para deixar o produto melhor + assinatura de até R$ 10

Data: 16/11/2026 (revisado no mesmo dia com a sua revisão). Complementa o relatório [validacao-mare.md](/mnt/project-files/mare/validacao-mare.md), que fica na pasta do projeto aqui no Claude, ao lado deste arquivo, e não dentro do repositório (por isso não aparece em `docs/`). As três correções de segurança estão descritas também na Fase 0 abaixo, então este roteiro se sustenta sozinho. Aqui o foco não é escalar, é deixar a Maré **mais útil, mais gostosa de usar e mais fácil de manter no dia a dia**. Nada do código foi alterado.

## A ideia central

Hoje a Maré responde bem a uma pergunta: **"essa fatura está certa?"**. Para a pessoa voltar todo mês, ela precisa responder mais três:

1. **"Como estou neste mês?"** (todos os cartões juntos, comparado com o mês passado)
2. **"Quanto do meu futuro já está gasto?"** (parcelas e assinaturas que vão continuar vindo)
3. **"Onde dá para cortar?"** (assinaturas esquecidas, categorias que subiram)

As fases abaixo seguem essa ordem. Cada uma cabe em 1 a 3 semanas de trabalho de uma pessoa e termina com algo que você consegue mostrar para alguém.

---

## Fase 0. Arrumar a casa (até 1 semana)

Coisas pequenas que evitam dor de cabeça depois.

- [x] **Branch nova** (por exemplo `fase-0`). O trabalho pendente está hoje em `docs/como-rodar-e-env-example`, que não é a branch certa para ele.
- [x] Revisar e commitar o que está pendente, **separado por assunto**: os 15 arquivos modificados e os 3 novos (`app/descricao.py` e `tests/test_apresentacao.py` num commit próprio, porque são a limpeza de CPF/CNPJ na saída da API).
- [ ] Limpar os 4 `.fuse_hidden*` de `data/` (sobras de um processo que segurava o banco aberto). **Pendente, é com você:** o assistente não tem permissão para apagar arquivos em `data/`. São 4 arquivos de 32 KB de 09/11, que não são bancos. Também dá para apagar `data/mare-backup-antes-v4.db*` e `data/mare-backup-antes-v6.db` quando você conferir que está tudo certo (eles guardam os dados crus, com CPF de terceiros).
- [x] As três correções de segurança (testes em `tests/test_fase0.py`):
  - **Limitador** (`app/seguranca.py:125`, `self._eventos.clear()`): ao passar de 5.000 chaves, ele zera também o contador do e-mail que alguém está tentando adivinhar. Agora sai primeiro o que expirou, depois quem não chegou ao limite e só por último quem já está bloqueado.
  - **CPF de terceiros cru no banco**: o `descricao.py` já limpa o que sai pela API, mas a descrição original continua gravada. Agora grava limpo. A comparação ao reimportar limpa os dois lados, senão duplicaria, e a migração 6 limpou o que já estava guardado (com cópia em `data/mare-backup-antes-v6.db`). Limite conhecido: depois de limpo, o banco já não sabe se o Pix era para pessoa física, então qualquer recategorização futura feita só com o texto guardado perde essa pista.
  - **"Desfazer" (`restaurar`)**: aceita qualquer categoria da lista completa, inclusive as fixas ("Pagamento de fatura", "Entradas"...). Agora aceita só as editáveis, e só atinge lançamentos de compra ou estorno.
- [ ] **Testes por banco (`tests/bancos/`)**: depende de você trazer faturas reais anonimizadas. Comece pelos bancos que você mesmo usa ou consegue com alguém próximo. O formato do Nubank ainda não foi confirmado, então ele é o primeiro da fila.

**Pronto quando:** os testes passam e cada banco que você conseguiu testar sai "Conferido".

## Fase 1. Primeira impressão (1 a 2 semanas)

Quem abre a Maré pela primeira vez ainda não tem o arquivo em mãos. Hoje a tela inicial pede um OFX e a pessoa trava.

- [ ] **Modo demonstração:** botão "Ver com uma fatura de exemplo" que carrega uma fatura fictícia. A pessoa vê a conferência, as categorias e as parcelas antes de ir atrás do arquivo.
- [ ] **"Como baixar no meu banco":** na tela de importar, uma lista de bancos e, ao clicar, o passo a passo curto (com print) de onde fica o "Exportar OFX" naquele app. É o ponto em que mais gente vai desistir. Comece só pelos bancos que entraram nos testes da Fase 0 e acrescente os outros conforme os testadores mandarem os prints.
- [ ] **Subir vários arquivos de uma vez:** arrastar a fatura do Nubank e a do Itaú juntas.
- [ ] **Divergência que explica:** quando a soma não bate, sugerir a causa provável ("parece faltar o IOF de R$ 3,21" ou "a diferença é igual ao saldo anterior") em vez de só mostrar "Divergente".

**Pronto quando:** uma pessoa que nunca viu a Maré consegue importar a primeira fatura sozinha, sem você explicar.

## Fase 2. "Como estou neste mês?" (2 a 3 semanas)

Esta é a fase que transforma a Maré de conferidor de fatura em app de finanças.

- [ ] **Tela "Este mês":** junta todos os cartões e contas do mês num número só, com a divisão por cartão e por categoria.
- [ ] **Comparação com o mês anterior** por categoria ("Alimentação: R$ 820, 18% a mais que outubro"). O backend já calcula a fatura anterior no `resumo`, então é estender o que existe.
- [ ] **Limite por categoria:** a pessoa define "Lazer até R$ 300" e vê uma barra enchendo. Sem notificação por enquanto, só a barra.
- [ ] **Gráfico de 6 meses** do gasto total, para ver a tendência.

**Pronto quando:** você mesmo passa a abrir a Maré para ver o mês, não só para conferir a fatura.

## Fase 3. "Quanto do meu futuro já está gasto?" (1 a 2 semanas)

É o diferencial que os concorrentes fazem mal, e a Maré já tem metade pronta (a tela de Parcelas).

- [ ] **Renda comprometida:** a pessoa informa a renda mensal (opcional) e a Maré mostra "dezembro já tem 34% da sua renda comprometida com parcelas".
- [ ] **Simulador "posso parcelar?":** digita "R$ 1.200 em 10x" e vê como ficam os próximos 10 meses somados ao que já existe.
- [ ] **Assinaturas detectadas:** a Maré percebe o que se repete todo mês (Netflix, Spotify, academia, iCloud) e mostra "você paga R$ 187/mês em 9 assinaturas". A categoria "Assinaturas" já existe; falta detectar a repetição entre faturas.
- [ ] **Fim de parcela:** "em março acabam 3 parcelas e sobram R$ 410 por mês". É uma notícia boa, e notícia boa faz a pessoa voltar.

**Pronto quando:** a tela de Parcelas responde "posso comprar isso parcelado?" sem a pessoa fazer conta.

## Fase 4. Criar o hábito (1 a 2 semanas)

O maior risco da Maré é a pessoa esquecer de subir a fatura. Esta fase ataca isso usando o SMTP que já está pronto.

**Decisão antes de começar: quem dispara o e-mail?** Hoje o app não tem nenhum processo em segundo plano. Minha sugestão é um **script separado chamado pelo agendador do servidor** (por exemplo `python -m app.lembretes`, rodando uma vez por dia pelo cron do Linux ou pelo Agendador de Tarefas do Windows). Ele é fácil de testar sozinho, não duplica e-mail se um dia o servidor rodar com mais de um processo e não cai junto com o site. Uma tarefa dentro do próprio uvicorn funciona no começo, mas para quando o servidor reinicia.

- [ ] **Lembrete no fechamento:** a Maré aprende o dia de fechamento de cada cartão pelas faturas já importadas e manda um e-mail "sua fatura do Nubank fechou, leva 1 minuto para subir".
- [ ] **Resumo mensal por e-mail:** gasto do mês, a categoria que mais subiu e as parcelas do próximo mês.
- [ ] **"Pendente":** na tela inicial, um aviso discreto "falta a fatura de novembro do Itaú".

**Pronto quando:** você recebe o lembrete do seu próprio cartão no dia certo.

## Fase 4.5. Antes de chamar testadores (1 semana)

Os testadores vão subir extratos reais, que são dado financeiro, e vão esquecer a senha. Isso precisa existir **antes** do primeiro convite, e não junto com a cobrança.

- [ ] **Esqueci minha senha**, reaproveitando o envio de código por e-mail que já existe.
- [ ] **Excluir conta** e **baixar meus dados** em CSV/JSON. São direitos do titular na LGPD.
- [ ] **Política de privacidade** curta e honesta: o que fica guardado (os lançamentos), o que não fica (o arquivo original), onde fica o servidor e como pedir exclusão.
- [ ] Ligar `CONFIRMAR_EMAIL=1` e `CADASTRO_ABERTO=1` só para quem tiver o link de convite.

**Pronto quando:** você convida as primeiras 20 pessoas. A meta é que pelo menos metade suba a fatura do mês seguinte depois do lembrete da Fase 4.

## Fase 5. Menos trabalho na entrada (2 a 3 semanas)

- [ ] **Importar PDF** para os bancos que não exportam OFX ou CSV. É o pedido mais provável no suporte.
- [ ] **Lançamento manual rápido** para dinheiro vivo e Pix fora dos extratos importados.
- [ ] **"Não é meu" e "dividir":** marcar uma compra como reembolsável (fiz para outra pessoa) ou dividir uma conta ao meio. Tira esses valores do gasto real.
- [ ] **Tela de regras:** ver e editar as regras de categoria que a Maré aprendeu ("tudo de 'posto shell' vai para Transporte").

## Fase 6. Pronto para cobrar (1 a 2 semanas)

Só depois de as fases 1 a 4 estarem de pé, porque é o que justifica pagar.

- [ ] Termos de uso (a política de privacidade já entrou na Fase 4.5).
- [ ] Reconferir as taxas do Asaas e da Stripe e o preço do Organizze no dia de decidir, porque mudam.
- [ ] Confirmar se você recebe como pessoa física ou se precisa abrir um MEI.
- [ ] Cobrança com webhook que liga e desliga o plano, e cancelamento em um clique.
- [ ] Separar grátis e pago no app (ver abaixo).

---

## Assinatura de até R$ 10

### O custo de cobrar com valor baixo

Num preço baixo, a **taxa fixa por cobrança** pesa muito mais que a porcentagem. Valores atuais:

| Meio | Taxa pública | Em R$ 9,90/mês | Em R$ 79/ano |
|---|---|---|---|
| **Asaas, cartão à vista** | R$ 0,49 + 2,99% (promoção de 3 meses para conta nova: R$ 0,49 + 1,99%) ([Asaas](https://www.asaas.com/precos-e-taxas)) | R$ 0,79 (8%) | R$ 2,85 (3,6%) |
| **Asaas, Pix** | R$ 2,15 por recebimento (promoção de 3 meses: R$ 1,08) ([Asaas](https://www.asaas.com/precos-e-taxas)) | R$ 2,15 (**22%**) | R$ 2,15 (2,7%) |
| **Stripe, cartão + Billing** | 3,99% + R$ 0,39, mais 0,7% do Billing (assinaturas) ([Stripe](https://stripe.com/br/pricing)) | R$ 0,85 (8,6%) | R$ 4,10 (5,2%) |
| **Stripe, Pix** | 1,19% por Pix pago ([Stripe](https://stripe.com/br/pricing)) | R$ 0,12 (1,2%)* | R$ 0,94 (1,2%)* |

\* Se a cobrança passar pelo Billing da Stripe, somam-se 0,7%. Não confirmei se a Stripe faz cobrança recorrente automática por Pix no Brasil. Para o plano anual isso não importa, porque é um pagamento só por ano. Não achei a tabela oficial de assinaturas do Mercado Pago, então ele ficou de fora da comparação.

**Conclusão:**
- **Mensal:** cobre no **cartão recorrente**, que custa cerca de 8%. Pix mensal pelo Asaas come 22% do valor.
- **Anual:** aceite **Pix e cartão**. Com um pagamento só por ano, a taxa cai para 1% a 4%.

### Proposta de planos

| | **Grátis** | **Maré** |
|---|---|---|
| Preço | R$ 0 | **R$ 9,90/mês** no cartão, ou **R$ 79/ano** no Pix ou cartão (dá R$ 6,58/mês) |
| Cartões e contas | 1 | Ilimitados |
| Histórico | Últimos 2 meses | Completo |
| Conferência da fatura e categorias | Sim | Sim |
| Tela "Este mês" e comparação | Só o mês atual | Com comparação e gráfico de 6 meses |
| Parcelas futuras | Só a lista | Com renda comprometida e simulador "posso parcelar?" |
| Assinaturas detectadas | Não | Sim |
| Lembrete de fechamento e resumo por e-mail | Não | Sim |
| Limite por categoria | Não | Sim |

- **14 dias do plano Maré grátis** para todo mundo que se cadastra, sem pedir cartão.
- **Anual em destaque** na tela de preço ("2 meses de graça").
- **Primeiros 50 assinantes:** R$ 59 no **primeiro ano**, em troca de feedback. Depois o preço passa a ser o normal, avisado com antecedência. Prometer "para sempre" seria um compromisso permanente, então prefiro deixar essa decisão para quando você tiver números. Isso valida o preço sem precisar de anúncio.

### Por que esse valor funciona

O Organizze Manual, que também não conecta no banco, cobra R$ 39/mês ou 12x R$ 29,90 no anual ([Organizze](https://www.organizze.com.br/planos/), lido em 16/11/2026). A Maré a R$ 9,90 custa um quarto disso. O plano grátis é bom o bastante para a pessoa sentir a conferência, mas o que ela quer usar todo mês (o mês inteiro, as parcelas com renda e o lembrete) fica no pago.

### A conta

Este cálculo é uma inferência, porque não pesquisei o preço de servidor e de domínio. Supondo uns R$ 80/mês de VPS, domínio e e-mail:

| Assinantes | Receita líquida/mês (metade mensal no cartão, metade anual) | Cobre a infra? |
|---|---|---|
| 15 | cerca de R$ 115 | Sim |
| 100 | cerca de R$ 770 | Sim, com folga |
| 500 | cerca de R$ 3.850 | Paga um agregador de Open Finance (a partir de R$ 2.500/mês) |

Um ponto a verificar fora do código: para receber como empresa você vai precisar de CNPJ (MEI serve). Confirme com o Asaas ou a Stripe se a sua conta pode receber assinaturas como pessoa física.

## Ordem resumida

| Fase | O que entrega | Tamanho |
|---|---|---|
| 0 | Arrumar a casa: branch nova, commits separados, 3 correções de segurança, testes com faturas reais | 1 semana (os testes por banco dependem das suas faturas) |
| 1 | Primeira impressão: fatura de exemplo, "como baixar no meu banco", vários arquivos, divergência que explica | 1 a 2 semanas |
| 2 | Tela "Este mês": cartões juntos, comparação, limite por categoria, gráfico de 6 meses | 2 a 3 semanas |
| 3 | Futuro comprometido: renda comprometida, "posso parcelar?", assinaturas detectadas | 1 a 2 semanas |
| 4 | Hábito: agendador, lembrete no fechamento, resumo mensal | 1 a 2 semanas |
| 4.5 | Antes dos testadores: esqueci a senha, excluir e baixar dados, política de privacidade. **Aqui entram as 20 pessoas.** | 1 semana |
| 6 | Cobrança: R$ 9,90/mês ou R$ 79/ano, grátis com limites, R$ 59 no 1º ano para os 50 primeiros | 1 a 2 semanas |
| 5 | PDF, lançamento manual, "dividir", tela de regras, guiado pelo que os testadores pedirem | 2 a 3 semanas |

## Fontes

- [Asaas, preços e taxas](https://www.asaas.com/precos-e-taxas) (lido em 16/11/2026)
- [Stripe Brasil, preços](https://stripe.com/br/pricing) (lido em 16/11/2026)
- [Organizze, planos](https://www.organizze.com.br/planos/) (lido em 16/11/2026)
- [Nação Digital, sistemas de cobrança 2026](https://nacao.digital/blog/sistema-de-cobranca/) (fonte secundária, usada só para conferir as promoções do Asaas)
- Código da Maré (`app/db.py`, `frontend/src/views/*`) e o estudo de mercado do projeto (preço da Pluggy)
