import { h, ico, novoId } from './dom.js';
import { dataBR } from './format.js';
import { logoSimbolo } from './logo.js';
import type { Ctx, FaturaResumo } from './types.js';

export function rotuloFatura(f: Pick<FaturaResumo, 'emissor' | 'vencimento' | 'referencia' | 'conta'>): string {
  const nome = (f.emissor || (f.conta ? 'Conta' : 'Cartão')) + (f.conta && f.emissor ? ' (conta)' : '');
  return f.vencimento ? `${nome}, vence ${dataBR(f.vencimento)}` : `${nome}, até ${dataBR(f.referencia)}`;
}

// Seleção de fatura compartilhada entre Resumo e Transações. Some quando só existe uma.
export function seletorFatura(ctx: Ctx): HTMLElement | null {
  const { state } = ctx;
  if (state.faturas.length < 2) return null;
  const id = novoId('fatura');
  const sel = h('select', {
    id,
    onchange: () => { ctx.escolherFatura(Number(sel.value)); },
  }, state.faturas.map((f) => h('option', { value: f.id, selected: f.id === state.faturaId }, rotuloFatura(f))));
  return h('div', { class: 'campo seletor-fatura' }, h('label', { for: id }, 'Fatura'), h('div', { class: 'seletor' }, sel));
}

export function selo(f: Pick<FaturaResumo, 'status' | 'conta'>): HTMLElement {
  if (f.conta) return h('span', { class: 'selo selo-neutro' }, ico('info'), 'Extrato');
  if (f.status === 'ok') return h('span', { class: 'selo selo-ok' }, ico('check-circle'), 'Conferida');
  if (f.status === 'divergente') return h('span', { class: 'selo selo-alerta' }, ico('warning'), 'Divergente');
  return h('span', { class: 'selo selo-neutro' }, ico('info'), 'Sem total');
}

export function semFaturas(_ctx?: Ctx): HTMLElement {
  return h('div', { class: 'vazio mare' },
    logoSimbolo('logo-simbolo logo-grande'),
    h('h1', {}, 'Nenhuma fatura ainda'),
    h('p', {}, 'Importe o arquivo OFX ou CSV da fatura do cartão. O app soma tudo, confere com o total e mostra para onde o dinheiro foi.'),
    h('a', { class: 'btn btn-primario', href: '#/faturas' }, 'Importar fatura'));
}

export function confirmar({ titulo, texto, ok = 'Excluir' }: { titulo: string; texto: string; ok?: string }): Promise<boolean> {
  const d = document.getElementById('confirmar') as HTMLDialogElement;
  (document.getElementById('confirmar-titulo') as HTMLElement).textContent = titulo;
  (document.getElementById('confirmar-texto') as HTMLElement).textContent = texto;
  (document.getElementById('confirmar-ok') as HTMLElement).textContent = ok;
  d.returnValue = '';
  return new Promise((resolve) => {
    d.addEventListener('close', () => resolve(d.returnValue === 'ok'), { once: true });
    d.showModal();
  });
}

export function esqueleto(linhas = 5): HTMLElement {
  return h('div', { class: 'esqueleto', 'aria-hidden': 'true' },
    h('div', { class: 'esq esq-linha', 'data-w': 'curto' }),
    h('div', { class: 'esq esq-bloco' }),
    ...Array.from({ length: linhas }, () => h('div', { class: 'esq esq-linha' })));
}
