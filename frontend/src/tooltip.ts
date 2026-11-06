// Tooltip único para dados de gráfico. Aparece com mouse ou foco de teclado, some com Esc e ao sair.
const tip = document.getElementById('tooltip') as HTMLElement;

interface ConteudoDica { titulo?: string; texto?: string }

function posicionar(alvo: HTMLElement): void {
  const r = alvo.getBoundingClientRect();
  const t = tip.getBoundingClientRect();
  let x = r.left + r.width / 2 - t.width / 2;
  x = Math.max(8, Math.min(x, window.innerWidth - t.width - 8));
  let y = r.top - t.height - 8;
  if (y < 8) y = r.bottom + 8;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

export function esconder(): void { tip.hidden = true; }

export function dica(alvo: HTMLElement, conteudo: ConteudoDica | (() => ConteudoDica)): void {
  const mostrar = () => {
    const c = typeof conteudo === 'function' ? conteudo() : conteudo;
    tip.replaceChildren();
    if (c.titulo) { const s = document.createElement('strong'); s.textContent = c.titulo; tip.append(s); }
    tip.append(document.createTextNode(c.texto || ''));
    tip.hidden = false;
    posicionar(alvo);
  };
  alvo.addEventListener('pointerenter', (e) => { if (e.pointerType !== 'touch') mostrar(); });
  alvo.addEventListener('pointerleave', esconder);
  alvo.addEventListener('focus', () => { if (alvo.matches(':focus-visible')) mostrar(); });
  alvo.addEventListener('blur', esconder);
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') esconder(); });
window.addEventListener('scroll', esconder, { passive: true });
