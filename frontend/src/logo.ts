// Símbolo da Maré (duas ondas e a lua), referenciado do sprite em index.html para herdar as cores do tema.
const NS = 'http://www.w3.org/2000/svg';
export function logoSimbolo(classe = 'logo-simbolo'): SVGSVGElement {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', classe);
  svg.setAttribute('aria-hidden', 'true');
  const uso = document.createElementNS(NS, 'use');
  uso.setAttribute('href', '#mare-simbolo');
  svg.append(uso);
  return svg;
}

// Logo em movimento: duas ondas senoidais (período 48) correm em sentidos opostos e a lua flutua. É o indicador de carregamento do app.
// A animação é CSS (classes .onda-* em app.css) e some com prefers-reduced-motion, deixando a logo parada.
function ondaPath(y: number, sobe: boolean): string {
  return `M-48 ${y} q12 ${sobe ? -12 : 12} 24 0${' t24 0'.repeat(8)}`;
}
let _onda = 0;
export function logoOnda(classe = 'logo-onda'): SVGSVGElement {
  const id = `onda-${++_onda}`; // ids únicos: vários indicadores podem existir ao mesmo tempo
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', classe);
  svg.setAttribute('viewBox', '0 0 96 96');
  svg.setAttribute('aria-hidden', 'true');
  const el = (nome: string, attrs: Record<string, string>, ...filhos: Element[]): SVGElement => {
    const e = document.createElementNS(NS, nome);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    e.append(...filhos);
    return e;
  };
  const grad = el('linearGradient', { id: `${id}-g`, x1: '0', x2: '1', y1: '0', y2: '0' },
    el('stop', { offset: '0', 'stop-color': '#fff', 'stop-opacity': '0' }), el('stop', { offset: '0.22', 'stop-color': '#fff' }),
    el('stop', { offset: '0.78', 'stop-color': '#fff' }), el('stop', { offset: '1', 'stop-color': '#fff', 'stop-opacity': '0' }));
  const mascara = el('mask', { id: `${id}-m`, maskUnits: 'userSpaceOnUse', x: '0', y: '0', width: '96', height: '96' },
    el('rect', { x: '10', y: '0', width: '68', height: '96', fill: `url(#${id}-g)` }));
  svg.append(
    el('defs', {}, grad, mascara),
    el('circle', { class: 'logo-c onda-lua', cx: '77', cy: '23', r: '8' }),
    el('g', { mask: `url(#${id}-m)` },
      el('g', { class: 'onda onda-a' }, el('path', { class: 'logo-a', d: ondaPath(54, true) })),
      el('g', { class: 'onda onda-b' }, el('path', { class: 'logo-b', d: ondaPath(77, false) }))));
  return svg;
}
