import { h } from './dom.js';

interface OpcoesToast { acao?: { rotulo: string; fn: () => unknown }; erro?: boolean; ms?: number }

// Aviso transitório que não rouba o foco (região aria-live="polite" no HTML). Ação opcional, como "Desfazer".
export function toast(mensagem: string, { acao, erro = false, ms }: OpcoesToast = {}): void {
  const area = document.getElementById('toasts');
  if (!area) return;
  const el = h('div', { class: `toast${erro ? ' toast-erro' : ''}` }, h('span', {}, mensagem));
  const fechar = () => el.remove();
  if (acao) {
    el.append(h('button', { type: 'button', onclick: async () => { fechar(); await acao.fn(); } }, acao.rotulo));
  }
  area.append(el);
  setTimeout(fechar, ms ?? (acao || erro ? 7000 : 4500));
}
