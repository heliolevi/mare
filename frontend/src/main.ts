import { h, ico } from './dom.js';
import { api, ApiError } from './api.js';
import { logoOnda } from './logo.js';
import { telaAcesso } from './views/entrar.js';
import { toast } from './toast.js';
import { esconder } from './tooltip.js';
import type { Ctx, Estado, FaturaResumo, Sessao, Tela, Usuario } from './types.js';

const CHAVE_FATURA = 'mare.fatura';
type NomeRota = 'resumo' | 'transacoes' | 'parcelas' | 'faturas';
const ROTAS: Record<NomeRota, () => Promise<{ default: Tela }>> = {
  resumo: () => import('./views/resumo.js'),
  transacoes: () => import('./views/transacoes.js'),
  parcelas: () => import('./views/parcelas.js'),
  faturas: () => import('./views/faturas.js'),
};
const TITULOS: Record<NomeRota, string> = { resumo: 'Resumo', transacoes: 'Transações', parcelas: 'Parcelas', faturas: 'Faturas' };

const main = document.getElementById('conteudo') as HTMLElement;
const state: Estado = { usuario: null, faturas: [], faturaId: null, categorias: [] };
const ehRota = (n: string): n is NomeRota => Object.hasOwn(ROTAS, n);
const msgErro = (e: unknown): string => (e instanceof Error ? e.message : 'Algo deu errado.');
let rota: NomeRota | 'nao-encontrada' = 'resumo';
let params = new URLSearchParams();
let geracao = 0; // descarta respostas de navegações que já foram superadas

function lerHash() {
  const bruto = location.hash.replace(/^#\/?/, '');
  const [nome = '', query = ''] = bruto.split('?');
  // Endereço vazio vai para o resumo; um nome que não existe mostra a página 404 em vez de fingir que era o resumo.
  rota = nome === '' ? 'resumo' : ehRota(nome) ? nome : 'nao-encontrada';
  params = new URLSearchParams(query);
}

function guardarFatura(id: number): void { try { localStorage.setItem(CHAVE_FATURA, String(id)); } catch { /* ignora */ } }
function fixarFatura() {
  let salvo = null;
  try { salvo = Number(localStorage.getItem(CHAVE_FATURA)) || null; } catch { /* ignora */ }
  const existe = (id: number | null): boolean => state.faturas.some((f) => f.id === id);
  if (!existe(state.faturaId)) state.faturaId = existe(salvo) ? salvo : state.faturas[0]?.id ?? null;
  if (state.faturaId != null) guardarFatura(state.faturaId);
}

async function carregarBase() {
  const [faturas, categorias] = await Promise.all([
    api<FaturaResumo[]>('/api/faturas'),
    state.categorias.length ? state.categorias : api<string[]>('/api/categorias'),
  ]);
  state.faturas = faturas;
  state.categorias = categorias;
}

const ctx: Ctx = {
  state,
  get params() { return params; },
  navegar(destino: string) { if (location.hash === destino) desenhar(); else location.hash = destino; },
  async recarregar(novoId?: number | null) {
    await carregarBase();
    if (novoId != null) state.faturaId = novoId;
    fixarFatura();
    await desenhar();
  },
  escolherFatura(id: number, redesenhar = true) {
    state.faturaId = id;
    guardarFatura(id);
    if (redesenhar) desenhar();
  },
};

function marcarNav() {
  document.querySelectorAll<HTMLAnchorElement>('.nav a[data-rota]').forEach((a) => {
    if (a.dataset.rota === rota) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  document.title = `${rota === 'nao-encontrada' ? 'Página não encontrada' : TITULOS[rota]} · Maré`;
}

async function desenhar({ focar = false } = {}): Promise<boolean> {
  const minha = ++geracao;
  esconder();
  marcarNav();
  main.classList.toggle('largo', rota === 'resumo' || rota === 'transacoes');
  main.setAttribute('aria-busy', 'true');
  // Se a tela demora, a logo em movimento aparece no lugar do esqueleto (a maré "carregando").
  const esq = setTimeout(() => { if (minha === geracao) main.replaceChildren(carregando()); }, 150);
  try {
    const el = rota === 'nao-encontrada' ? naoEncontrada() : await (await ROTAS[rota]()).default(ctx);
    if (minha !== geracao) return false;
    main.replaceChildren(el);
  } catch (err) {
    if (minha !== geracao) return false;
    if (err instanceof ApiError && err.status === 401) return false;
    main.replaceChildren(h('div', { class: 'vazio' },
      ico('warning-circle'),
      h('h1', {}, 'Não foi possível carregar'),
      h('p', {}, msgErro(err)),
      h('button', { class: 'btn btn-secundario', type: 'button', onclick: () => desenhar() }, 'Tentar de novo')));
  } finally {
    clearTimeout(esq);
    if (minha === geracao) main.removeAttribute('aria-busy');
  }
  if (focar) {
    const t = main.querySelector('h1');
    if (t) { t.setAttribute('tabindex', '-1'); t.focus({ preventScroll: true }); }
  }
  return true;
}

function carregando(): HTMLElement {
  return h('div', { class: 'carregando', role: 'status' }, logoOnda('logo-onda'), h('span', { class: 'sr-only' }, 'Carregando…'));
}

function naoEncontrada(): HTMLElement {
  return h('div', { class: 'vazio mare' },
    logoOnda('logo-onda logo-onda-media'),
    h('p', { class: 'erro-codigo', 'aria-hidden': 'true' }, '404'),
    h('h1', {}, 'Página não encontrada'),
    h('p', {}, 'A maré levou esse endereço. Ele pode ter mudado de lugar ou nunca ter existido.'),
    h('a', { class: 'btn btn-primario', href: '#/resumo' }, 'Voltar ao resumo'));
}

function aoMudarRota() {
  lerHash();
  window.scrollTo(0, 0);
  desenhar({ focar: true });
}

function tirarSplash(): void {
  const sp = document.getElementById('splash');
  if (!sp) return;
  sp.classList.add('saindo');
  // Remove depois da transição; com movimento reduzido a transição é instantânea e o transitionend não dispara.
  setTimeout(() => sp.remove(), 450);
}

// A tela de abertura fica pelo menos o tempo de uma ou duas ondas, para a animação ser vista e não piscar.
const inicio = performance.now();
const reduzido = matchMedia('(prefers-reduced-motion: reduce)').matches;
async function revelar(): Promise<void> {
  const resta = (reduzido ? 300 : 1100) - (performance.now() - inicio);
  if (resta > 0) await new Promise((r) => setTimeout(r, resta));
  tirarSplash();
}

function mostrarAcesso(cadastroAberto: boolean, mensagem = ''): void {
  geracao++;
  state.usuario = null;
  state.faturas = [];
  state.faturaId = null;
  try { localStorage.removeItem(CHAVE_FATURA); } catch { /* ignora */ }
  document.body.classList.add('sem-nav', 'tela-acesso');
  main.className = '';
  main.removeAttribute('aria-busy');
  main.replaceChildren(telaAcesso({
    cadastroAberto, mensagem,
    aoEntrar: async (u) => { await iniciar(u); },
  }));
}

async function iniciar(u: Usuario): Promise<void> {
  state.usuario = u;
  await carregarBase();
  document.body.classList.remove('sem-nav', 'tela-acesso');
  const nome = document.getElementById('nav-usuario');
  if (nome) { nome.textContent = u.nome; nome.title = u.email; }
  fixarFatura();
  lerHash();
  await desenhar();
}

async function sair(): Promise<void> {
  try { await api('/api/auth/sair', { method: 'POST' }); } catch { /* o cookie vence sozinho; segue para a tela de acesso */ }
  mostrarAcesso(await cadastroAberto());
}

async function cadastroAberto(): Promise<boolean> {
  try { return (await api<Sessao>('/api/auth/eu')).cadastro_aberto; } catch { return false; }
}

document.getElementById('sair')?.addEventListener('click', () => { void sair(); });
window.addEventListener('auth-required', () => {
  void cadastroAberto().then((aberto) => mostrarAcesso(aberto, 'Sua sessão terminou. Entre de novo para continuar.'));
});
window.addEventListener('hashchange', aoMudarRota);
window.addEventListener('offline', () => toast('Você está sem conexão. Dá para ver o que já carregou, mas não importar.', { erro: true }));

(async () => {
  try {
    const sessao = await api<Sessao>('/api/auth/eu');
    if (!sessao.usuario) mostrarAcesso(sessao.cadastro_aberto);
    else await iniciar(sessao.usuario);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return;
    main.replaceChildren(h('div', { class: 'vazio' },
      ico('warning-circle'),
      h('h1', {}, 'Servidor fora do ar'),
      h('p', {}, 'Não consegui falar com o servidor. Confira se ele está rodando e tente de novo.'),
      h('button', { class: 'btn btn-secundario', type: 'button', onclick: () => location.reload() }, 'Recarregar')));
    main.removeAttribute('aria-busy');
  }
  await revelar();
})();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => { /* PWA é opcional */ }));
}
