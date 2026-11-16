# Design da Maré

A Maré segue o manual de marca da HL ("oceano profundo"). O app é uma ferramenta de trabalho, então o mundo visual entra por tipo, paleta, densidade e um gesto de assinatura, nunca por layout ou controles.

## Cores: três, e só três

| Cor | Escuro | Claro | Faz o quê |
|---|---|---|---|
| **Marinho** | `#06101f` fundo, `#0b1a2f` superfície | `#f4f7fb` fundo, `#ffffff` superfície | Estrutura. Fundos, linhas e textos saem todos dele (neutros tingidos de azul, nunca cinza puro). |
| **Ciano** (HL) | `#22c3e6` | `#0b6880` | Ação, foco, link, seleção e **dinheiro que entra** (`+R$`). Também o selo "Conferida". |
| **Vermelho-coral** | `#ff6b6b` | `#c62f3a` | **Dinheiro que sai** (`−R$`): gastos, total da fatura, barras de categoria e de parcelas. Também alertas ("Divergente"). |

- Não existem verde nem âmbar. Conferido = ciano; problema = vermelho, sempre com ícone e texto.
- Dinheiro nunca depende só da cor: saída leva `−` (sinal de menos U+2212), entrada leva `+`. Pagamento de fatura e aplicações (só mudam o dinheiro de lugar) ficam neutros, sem sinal.
- Tokens: `--money-out`, `--money-in`, `--bar` (barras = vermelho 78%). Na faixa marinha da conferência o vermelho clareia para `--band-money` `#ff8f87`.
- Contrastes conferidos por cálculo: texto 4.5:1 ou mais e bordas de controle 3:1 ou mais, nos dois temas.
- Dark é o padrão; o claro entra quando o sistema pede. Separação por hairline de 1px, sem sombras. Cantos: 4px (tags), 8px (controles), 14px (painéis). Espaço: grade de 4px.

## Lançamentos

A API nunca devolve a descrição crua do banco: `app/descricao.py` tira CPF, CNPJ, agência e conta e separa **título** (quem recebeu, capitalizado) de **detalhe** ("Pix enviado · Banco do Brasil"). A linha mostra título em negrito, detalhe embaixo, categoria e valor com sinal. Cada dia tem o subtotal de saídas no cabeçalho, e o topo da lista mostra saídas, entradas e saldo do que está filtrado.

## Logo

O símbolo da Maré são duas ondas subindo em direção à lua, com o wordmark "maré" em Lexend Exa minúsculo (tracking -0.03em). Arquivos em `static/logo`: `mare-simbolo.svg` (fundo escuro), `mare-simbolo-claro.svg`, `mare-icone.svg` e `favicon.svg` (traço mais grosso para 40px ou menos). Na interface o símbolo vem de um sprite inline e troca de cor com o tema: espuma e ciano no escuro, azul-tinta e teal no claro. Aparece no menu lateral (desktop), na barra do topo (celular), no estado inicial e na tela de entrada. Os PNGs do PWA saem de `tools/make_icons.py`, com a mesma geometria.

## Tipografia

Lexend Exa 500 nos títulos e no wordmark em minúsculas, Manrope no texto, JetBrains Mono em labels, datas, tags e todos os valores em reais (algarismos tabulares). Fontes hospedadas em `static/fonts` (OFL).

## Gesto de assinatura: a conferência

O painel de conferência é um bloco de log em azul-marinho: linhas com pontilhado, valores em mono, soma, total e o selo de resultado. Depois de importar ou informar o total, as linhas aparecem em sequência (o único movimento autoral do app). `prefers-reduced-motion` desliga a animação.

## Textura

A textura **Maré** (gradiente fluido com grão) aparece só no estado inicial e na tela de entrada, uma por composição.

## Acessibilidade

Contrastes conferidos (texto 4.5:1 ou mais, bordas de controle e barras 3:1 ou mais) nos dois temas. Alvos de toque de 44px, foco por `box-shadow`, rótulos visíveis em todos os campos, erro junto do campo, tooltip também por teclado, navegação inferior no celular e lateral no desktop.
