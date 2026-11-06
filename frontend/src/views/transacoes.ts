import { h, ico, novoId } from '../dom.js';
import { api } from '../api.js';
import { brl, brlNegativo, diaExtenso, dm, plural, semAcento } from '../format.js';
import { toast } from '../toast.js';
import { seletorFatura, semFaturas } from '../componentes.js';
import type { Ctx, Fatura, TrocaCategoria, Transacao } from '../types.js';

type FiltroTipo = '' | 'compra' | 'parcela' | 'estorno' | 'encargo' | 'entrada';
type Ordem = 'data' | 'maior' | 'nome';
interface Filtro { q: string; cat: string; tipo: FiltroTipo; ordem: Ordem }

const TIPOS: readonly (readonly [FiltroTipo, string])[] = [['', 'Tudo'], ['compra', 'Compras'], ['parcela', 'Parceladas'], ['estorno', 'Estornos'], ['encargo', 'Encargos'], ['entrada', 'Entradas']];
const col = new Intl.Collator('pt-BR');
const ORDENS: readonly (readonly [Ordem, string])[] = [['data', 'Mais recentes'], ['maior', 'Maior valor'], ['nome', 'Nome (A–Z)']];
const PASSO = 40;
const msgErro = (e: unknown): string => (e instanceof Error ? e.message : 'Algo deu errado.');

const ROTULO_TIPO: Record<string, string> = { pagamento: 'Pagamento', estorno: 'Estorno', encargo: 'Juros e taxas', saldo_anterior: 'Saldo anterior', entrada: 'Entrada' };
const CREDITOS = new Set(['estorno', 'pagamento', 'entrada']);

export default async function transacoes(ctx: Ctx): Promise<HTMLElement> {
  const { state } = ctx;
  if (!state.faturas.length || state.faturaId == null) return semFaturas(ctx);
  const fat = await api<Fatura>(`/api/faturas/${state.faturaId}`);
  const tipoUrl = ctx.params.get('tipo');
  const ordemUrl = ctx.params.get('ordem');
  const filtro: Filtro = {
    q: ctx.params.get('q') || '',
    cat: ctx.params.get('cat') || '',
    tipo: TIPOS.find(([v]) => v === tipoUrl)?.[0] ?? '',
    ordem: ORDENS.find(([v]) => v === ordemUrl)?.[0] ?? 'data',
  };
  let limite = PASSO;

  const idBusca = novoId('busca');
  const idCat = novoId('cat');
  const busca = h('input', { class: 'entrada', id: idBusca, type: 'search', autocomplete: 'off', placeholder: 'Nome do estabelecimento', value: filtro.q });
  const catsPresentes = (): string[] => [...new Set(fat.transacoes.map((t) => t.categoria))].sort(col.compare);
  if (filtro.cat && !catsPresentes().includes(filtro.cat)) filtro.cat = '';
  const selCat = h('select', { id: idCat });
  function desenharCategorias(): void {
    const cats = catsPresentes();
    if (filtro.cat && !cats.includes(filtro.cat)) filtro.cat = '';
    selCat.replaceChildren(h('option', { value: '' }, 'Todas'), ...cats.map((c) => h('option', { value: c, selected: c === filtro.cat }, c)));
    selCat.value = filtro.cat;
  }
  desenharCategorias();

  const idOrdem = novoId('ordem');
  const selOrdem = h('select', { id: idOrdem }, ORDENS.map(([v, r]) => h('option', { value: v, selected: v === filtro.ordem }, r)));
  const tipos = h('div', { class: 'segmentos', role: 'group', 'aria-label': 'Tipo de lançamento' });
  const ativos = h('div', { class: 'ativos' });
  const ehConta = fat.conta;
  const tiposPresentes = (): [FiltroTipo, string][] => TIPOS
    .filter(([v]) => v === '' || v === filtro.tipo
      || (v === 'parcela' ? fat.transacoes.some((t) => !!t.parcela_total) : fat.transacoes.some((t) => t.tipo === v)))
    .map(([v, r]) => [v, v === 'compra' && ehConta ? 'Saídas' : r]);
  const contagem = h('p', { class: 'contagem', 'aria-live': 'polite' });
  const lista = h('div', { class: 'lista-tx' });

  function sincronizarUrl() {
    const p = new URLSearchParams();
    if (filtro.q) p.set('q', filtro.q);
    if (filtro.cat) p.set('cat', filtro.cat);
    if (filtro.tipo) p.set('tipo', filtro.tipo);
    if (filtro.ordem !== 'data') p.set('ordem', filtro.ordem);
    const s = p.toString();
    history.replaceState(null, '', `#/transacoes${s ? `?${s}` : ''}`);
  }

  function visiveis() {
    const q = semAcento(filtro.q.trim());
    const porTipo = (t: Transacao): boolean => !filtro.tipo || (filtro.tipo === 'parcela' ? !!t.parcela_total : t.tipo === filtro.tipo);
    const cmpData = (a: Transacao, b: Transacao): number => (a.data < b.data ? 1 : a.data > b.data ? -1 : b.id - a.id);
    const cmp: (a: Transacao, b: Transacao) => number = filtro.ordem === 'maior' ? (a, b) => b.valor_cents - a.valor_cents || cmpData(a, b)
      : filtro.ordem === 'nome' ? (a, b) => col.compare(a.descricao, b.descricao) || cmpData(a, b)
      : cmpData;
    return fat.transacoes
      .filter((t) => porTipo(t) && (!filtro.cat || t.categoria === filtro.cat) && (!q || semAcento(t.descricao).includes(q)))
      .sort(cmp);
  }

  function limpar() {
    Object.assign(filtro, { q: '', cat: '', tipo: '' });
    busca.value = ''; selCat.value = ''; limite = PASSO;
    sincronizarUrl(); desenhar();
  }

  function desenharControles() {
    tipos.replaceChildren(...tiposPresentes().map(([v, r]) => h('button', {
      type: 'button', class: 'segmento', 'aria-pressed': String(v === filtro.tipo),
      onclick: () => { filtro.tipo = v; limite = PASSO; sincronizarUrl(); desenhar(); },
    }, r)));
    const chips: [string, () => void][] = [];
    if (filtro.q) chips.push(['Busca: ' + filtro.q, () => { filtro.q = ''; busca.value = ''; }]);
    if (filtro.cat) chips.push([filtro.cat, () => { filtro.cat = ''; selCat.value = ''; }]);
    ativos.replaceChildren(...chips.map(([r, fn]) => h('button', {
      type: 'button', class: 'chip', 'aria-label': `Remover filtro ${r}`,
      onclick: () => { fn(); limite = PASSO; sincronizarUrl(); desenhar(); },
    }, r, ico('x'))));
    if (chips.length || filtro.tipo) ativos.append(h('button', { type: 'button', class: 'btn-texto', onclick: limpar }, 'Limpar tudo'));
  }

  function desenhar(focoId?: number, focoPrimeiroNovo?: number): void {
    desenharControles();
    const itens = visiveis();
    const gasto = itens.reduce((s, t) => s + (t.tipo === 'estorno' ? -t.valor_cents : ['compra', 'encargo'].includes(t.tipo) ? t.valor_cents : 0), 0);
    contagem.textContent = itens.length
      ? `${plural(itens.length, 'lançamento', 'lançamentos')}${gasto > 0 ? `, ${brl(gasto)} em ${ehConta ? 'saídas' : 'gastos'}` : ''}`
      : '';
    if (!itens.length) {
      lista.replaceChildren(h('div', { class: 'vazio' },
        ico('magnifying-glass'),
        h('h2', {}, 'Nenhum lançamento encontrado'),
        h('p', {}, 'Nada bate com esses filtros nesta fatura.'),
        h('button', { class: 'btn btn-secundario', type: 'button', onclick: limpar }, 'Limpar filtros')));
      return;
    }
    const grupos = new Map();
    const pagina = itens.slice(0, limite);
    for (const t of pagina) { if (!grupos.has(t.data)) grupos.set(t.data, []); grupos.get(t.data).push(t); }
    lista.replaceChildren(...[...grupos].map(([data, ts]) => h('section', { class: 'dia', 'aria-label': diaExtenso(data) },
      h('h3', {}, diaExtenso(data)), ...ts.map(linha))));
    if (itens.length > pagina.length) {
      lista.append(h('div', { class: 'mais' },
        h('p', {}, `Mostrando ${pagina.length} de ${itens.length}`),
        h('button', { class: 'btn btn-secundario', type: 'button', onclick: () => { const ant = limite; limite += PASSO; desenhar(undefined, ant); } }, 'Mostrar mais')));
    }
    if (focoId) lista.querySelector<HTMLSelectElement>(`[data-tx="${focoId}"] select`)?.focus();
    if (focoPrimeiroNovo != null) {
      const novo = itens[focoPrimeiroNovo];
      const el = novo && lista.querySelector<HTMLElement>(`[data-tx="${novo.id}"]`);
      if (el) { el.tabIndex = -1; el.focus({ preventScroll: false }); }
    }
  }

  function linha(t: Transacao): HTMLElement {
    const credito = CREDITOS.has(t.tipo);
    const valor = t.tipo === 'entrada' ? `+${brl(t.valor_cents)}` : credito ? brlNegativo(t.valor_cents) : brl(t.valor_cents);
    const editavel = t.tipo === 'compra' || t.tipo === 'estorno';
    let controle;
    if (editavel) {
      const sel: HTMLSelectElement = h('select', { 'aria-label': `Categoria de ${t.descricao}`, onchange: () => trocar(t, sel) },
        // A categoria atual entra na lista mesmo se for removida das editáveis, para o select não mentir.
        (state.categorias.includes(t.categoria) ? state.categorias : [t.categoria, ...state.categorias]).map((c) => h('option', { value: c, selected: c === t.categoria }, c)));
      controle = h('span', { class: 'cat-troca' }, sel);
    } else {
      controle = h('span', { class: 'cat-fixa' }, t.tipo === 'interno' ? t.categoria : (ROTULO_TIPO[t.tipo] || t.categoria));
    }
    return h('article', { class: `tx${credito ? ' tx-credito' : ''}${t.tipo === 'pagamento' || t.tipo === 'interno' ? ' tx-apagado' : ''}`, 'data-tx': t.id },
      h('span', { class: 'tx-data num' }, dm(t.data)),
      h('span', { class: 'tx-desc' }, t.descricao,
        t.parcela_total ? h('span', { class: 'etiqueta' }, `${t.parcela_atual}/${t.parcela_total}`) : null,
        t.tipo === 'estorno' ? h('span', { class: 'etiqueta' }, 'Estorno') : null),
      h('span', { class: 'tx-cat' }, controle),
      h('span', { class: 'tx-valor num' }, valor));
  }

  async function trocar(t: Transacao, sel: HTMLSelectElement): Promise<void> {
    const nova = sel.value;
    const anterior = t.categoria;
    t.categoria = nova;
    try {
      const r = await api<TrocaCategoria>(`/api/transacoes/${t.id}`, { method: 'PATCH', json: { categoria: nova } });
      for (const a of r.anteriores) { const o = fat.transacoes.find((x) => x.id === a.id); if (o) o.categoria = nova; }
      desenharCategorias();
      desenhar(t.id);
      const outros = r.atualizadas - 1;
      toast(outros > 0 ? `${t.descricao} e mais ${plural(outros, 'parecido', 'parecidos')} agora são ${nova}.` : `${t.descricao} agora é ${nova}.`, {
        acao: {
          rotulo: 'Desfazer',
          fn: async () => {
            try {
              await api('/api/transacoes/restaurar', { method: 'POST', json: { itens: r.anteriores, chave: r.chave, categoria_regra: r.categoria_anterior } });
              for (const a of r.anteriores) { const o = fat.transacoes.find((x) => x.id === a.id); if (o) o.categoria = a.categoria; }
              desenharCategorias();
              desenhar(t.id);
            } catch (err) { toast(msgErro(err), { erro: true }); }
          },
        },
      });
    } catch (err) {
      t.categoria = anterior;
      sel.value = anterior;
      toast(msgErro(err), { erro: true });
    }
  }

  let espera: ReturnType<typeof setTimeout> | undefined;
  busca.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(() => { filtro.q = busca.value; limite = PASSO; sincronizarUrl(); desenhar(); }, 120); });
  selCat.addEventListener('change', () => { filtro.cat = selCat.value; limite = PASSO; sincronizarUrl(); desenhar(); });
  selOrdem.addEventListener('change', () => { filtro.ordem = selOrdem.value as Ordem; sincronizarUrl(); desenhar(); });
  desenhar();

  return h('div', {},
    h('div', { class: 'topo' },
      h('div', { class: 'topo-texto' }, h('h1', {}, 'Transações'), h('p', {}, 'Trocar a categoria de um lançamento vale para os parecidos, inclusive nos próximos arquivos.')),
      seletorFatura(ctx)),
    h('div', { class: 'filtros' },
      h('div', { class: 'campo' }, h('label', { for: idBusca }, 'Buscar'), h('div', { class: 'com-icone' }, ico('magnifying-glass'), busca)),
      h('div', { class: 'campo' }, h('label', { for: idCat }, 'Categoria'), h('div', { class: 'seletor' }, selCat)),
      h('div', { class: 'campo' }, h('label', { for: idOrdem }, 'Ordenar por'), h('div', { class: 'seletor' }, selOrdem))),
    tipos, ativos, contagem, lista);
}
