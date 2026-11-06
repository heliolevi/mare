# Design da Maré

A Maré segue o manual de marca da HL ("oceano profundo"). O app é uma ferramenta de trabalho, então o mundo visual entra por tipo, paleta, densidade e um gesto de assinatura, nunca por layout ou controles.

## Tokens

- **Dark é o padrão** (azul-abismo `#050b1c`); o light entra quando o sistema pede (`#f4f8fb`).
- Interface: `bg`, `surface`, `surface-2`, `line`, `line-strong`, `ink`, `ink-muted`, `cyan`. Oceano (`ocean-*`) é fixo nos dois temas.
- Ciano é um ponto de luz por tela: CTA, foco, link, o nó do wordmark. Barras de dados usam cobalto; estados usam `ok`, `warn`, `danger`.
- Separação por hairline de 1px, sem sombras. A única luz é o `cyan-glow` no botão primário.
- Cantos: 4px (tags), 8px (controles), 14px (painéis). Pílula só no selo de status.
- Espaço: grade de 4px.

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
