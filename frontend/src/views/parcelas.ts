import { h, ico } from '../dom.js';
import { api } from '../api.js';
import { brl, mesCurto, mesLongo, plural } from '../format.js';
import { dica } from '../tooltip.js';
import { semFaturas } from '../componentes.js';
import type { Ctx, ParcelasFuturas } from '../types.js';

const LIMITE_GRAFICO = 12;
const LIMITE_ITENS = 40;

export default async function parcelas(ctx: Ctx): Promise<HTMLElement> {
  if (!ctx.state.faturas.length) return semFaturas(ctx);
  const dados = await api<ParcelasFuturas>('/api/parcelas-futuras');
  const topo = h('div', { class: 'topo' }, h('div', { class: 'topo-texto' }, h('h1', {}, 'Parcelas a vencer')));

  if (!dados.meses.length) {
    return h('div', {}, topo, h('div', { class: 'vazio' },
      ico('calendar-dots'),
      h('h2', {}, 'Nenhuma parcela pela frente'),
      h('p', {}, 'As compras parceladas aparecem aqui quando o arquivo traz o número da parcela, como 3/10 na descrição.')));
  }

  const compras = new Set(dados.meses.flatMap((m) => m.itens.map((i) => `${i.emissor}|${i.descricao}`))).size;
  topo.querySelector('.topo-texto')?.append(h('p', {}, `${brl(dados.total_cents)} já assumidos em ${plural(compras, 'compra parcelada', 'compras parceladas')}, com base na fatura mais recente de cada cartão.`));

  const visiveis = dados.meses.slice(0, LIMITE_GRAFICO);
  const max = Math.max(1, ...visiveis.map((m) => m.total_cents));
  let escolhido = 0;
  const detalhe = h('div', { class: 'detalhe-mes', 'aria-live': 'polite' });
  const botoes: HTMLButtonElement[] = [];

  function mostrarDetalhe() {
    const m = visiveis[escolhido];
    if (!m) return;
    detalhe.replaceChildren(
      h('h2', {}, mesLongo(m.mes)),
      h('p', { class: 'muted' }, `${brl(m.total_cents)} em ${plural(m.itens.length, 'parcela', 'parcelas')}`),
      h('ul', { class: 'maiores' }, [...m.itens].sort((a, b) => b.valor_cents - a.valor_cents).slice(0, LIMITE_ITENS).map((i) => h('li', { class: 'linha-item' },
        h('span', { class: 'desc' }, i.descricao),
        h('span', { class: 'valor num' }, brl(i.valor_cents)),
        h('span', { class: 'meta' }, h('span', { class: 'etiqueta' }, `Parcela ${i.parcela}`), i.emissor ? h('span', {}, i.emissor) : null)))),
      ...(m.itens.length > LIMITE_ITENS ? [h('p', { class: 'dica' }, `Mostrando ${LIMITE_ITENS} de ${m.itens.length} parcelas, as maiores primeiro.`)] : []));
    botoes.forEach((b, i) => b.setAttribute('aria-pressed', String(i === escolhido)));
  }

  const colunas = h('div', { class: 'colunas', role: 'group', 'aria-label': 'Total de parcelas por mês' });
  visiveis.forEach((m, i) => {
    const barra = h('span', { class: 'coluna' });
    barra.style.setProperty('--h', ((m.total_cents / max) * 100).toFixed(1));
    const b = h('button', {
      class: 'coluna-bt', type: 'button', 'aria-pressed': 'false',
      'aria-label': `${mesLongo(m.mes)}: ${brl(m.total_cents)} em ${plural(m.itens.length, 'parcela', 'parcelas')}`,
      onclick: () => { escolhido = i; mostrarDetalhe(); },
    }, barra);
    dica(b, () => ({ titulo: mesLongo(m.mes), texto: `${brl(m.total_cents)}, ${plural(m.itens.length, 'parcela', 'parcelas')}` }));
    botoes.push(b);
    colunas.append(b);
  });
  const rotulos = h('div', { class: 'meses', 'aria-hidden': 'true' }, visiveis.map((m) => h('span', {}, mesCurto(m.mes))));

  mostrarDetalhe();
  const maior = visiveis.reduce((a, m) => (m.total_cents > a.total_cents ? m : a));
  return h('div', {}, topo,
    h('p', { class: 'muted' }, `O maior mês é ${mesLongo(maior.mes)}, com ${brl(maior.total_cents)}.`),
    h('div', { class: 'secao' }, colunas, rotulos),
    dados.meses.length > LIMITE_GRAFICO ? h('p', { class: 'dica' }, `O gráfico mostra os ${LIMITE_GRAFICO} primeiros meses. A tabela abaixo tem todos.`) : null,
    h('div', { class: 'secao' }, detalhe),
    h('details', { class: 'secao' },
      h('summary', {}, 'Ver valores por mês em tabela'),
      h('div', { class: 'tabela-meses' }, dados.meses.map((m) => h('div', { class: 'linha-item' },
        h('span', { class: 'desc' }, mesLongo(m.mes)), h('span', { class: 'valor num' }, brl(m.total_cents)))))));
}
