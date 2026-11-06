import { h, ico, novoId } from '../dom.js';
import { api } from '../api.js';
import { brl, brlNegativo, dataBR, dm, plural } from '../format.js';
import { dica } from '../tooltip.js';
import { toast } from '../toast.js';
import { seletorFatura, semFaturas } from '../componentes.js';
import type { Ctx, Fatura, ResumoFatura } from '../types.js';

const msgErro = (e: unknown): string => (e instanceof Error ? e.message : 'Algo deu errado.');

const CHAVE_REVELAR = 'mare.revelar';
function consumirRevelar(id: number): boolean {
  try {
    if (sessionStorage.getItem(CHAVE_REVELAR) === String(id)) { sessionStorage.removeItem(CHAVE_REVELAR); return true; }
  } catch { /* sem sessionStorage */ }
  return false;
}
export function pedirRevelar(id: number): void { try { sessionStorage.setItem(CHAVE_REVELAR, String(id)); } catch { /* ignora */ } }

export default async function resumo(ctx: Ctx): Promise<HTMLElement> {
  const { state } = ctx;
  if (!state.faturas.length || state.faturaId == null) return semFaturas(ctx);
  const id = state.faturaId;
  const [fat, res] = await Promise.all([api<Fatura>(`/api/faturas/${id}`), api<ResumoFatura>(`/api/resumo?fatura_id=${id}`)]);
  const revelar = consumirRevelar(id);

  const sub = fat.conta ? `Extrato da conta, até ${dataBR(fat.referencia)}`
    : fat.vencimento ? `Vence em ${dataBR(fat.vencimento)}` : `Lançamentos até ${dataBR(fat.referencia)}`;
  const topo = h('div', { class: 'topo' },
    h('div', { class: 'topo-texto' }, h('h1', {}, fat.emissor || (fat.conta ? 'Conta' : 'Cartão de crédito')), h('p', {}, sub)),
    seletorFatura(ctx));

  const lado = h('div', { class: 'lado' }, ledger(fat, ctx, revelar));
  if (fat.avisos.length) {
    lado.append(h('ul', { class: 'avisos', 'aria-label': 'Observações sobre o arquivo' },
      fat.avisos.map((a) => h('li', {}, ico('info'), h('span', {}, a)))));
  }

  const principal = h('div', { class: 'principal' }, categorias(res), maiores(res, fat.conta));
  return h('div', {}, topo, h('div', { class: 'resumo-grade' }, lado, principal));
}

function ledger(fat: Fatura, ctx: Ctx, revelar: boolean): HTMLElement {
  const r = fat.reconciliacao;
  let n = 0;
  const linha = (nome: string, valor: string, cls = '') => {
    const el = h('div', { class: `leader ${cls}`.trim() }, h('dt', {}, nome), h('dd', { class: 'num' }, valor));
    el.style.setProperty('--n', String(n++));
    return el;
  };
  const regua = () => { const el = h('hr', { class: 'regua' }); el.style.setProperty('--n', String(n++)); return el; };

  const itens = h('dl', { class: 'ledger-linhas' }, linha(fat.conta ? 'Saídas' : 'Compras', brl(r.compras_cents)));
  if (r.encargos_cents) itens.append(linha('Juros, taxas e IOF', brl(r.encargos_cents)));
  if (r.saldo_anterior_cents) itens.append(linha('Saldo da fatura anterior', brl(r.saldo_anterior_cents)));
  if (r.estornos_cents) itens.append(linha('Estornos e créditos', brlNegativo(r.estornos_cents)));

  const fecho = h('dl', { class: 'ledger-linhas' });
  if (fat.conta) {
    fecho.append(linha('Total de saídas', brl(r.soma_cents), 'total'));
  } else if (r.status === 'sem_total') {
    fecho.append(linha('Soma das transações', brl(r.soma_cents), 'total'));
  } else {
    fecho.append(linha('Soma das transações', brl(r.soma_cents), 'forte'));
    fecho.append(linha('Total da fatura', brl(r.total_cents), 'total'));
  }

  const el = h('section', { class: `ledger${revelar ? ' revelar' : ''}`, 'aria-labelledby': 'tit-ledger' },
    h('h2', { id: 'tit-ledger' }, fat.conta ? 'Resumo do extrato' : 'Conferência da fatura'), itens, regua(), fecho);

  const notas: string[] = [];
  if (r.pagamentos_cents) notas.push(`Pagamentos recebidos (${brl(r.pagamentos_cents)}) ficam fora da conta.`);
  if (r.entradas_cents) notas.push(`Entradas (${brl(r.entradas_cents)}) não entram nas saídas.`);
  if (r.internos_cents) notas.push(`Movimentos internos, como pagamento de fatura e investimentos (${brl(r.internos_cents)}), também ficam de fora.`);
  for (const texto of notas) {
    const nota = h('p', { class: 'ledger-nota' }, texto);
    nota.style.setProperty('--n', String(n++));
    el.append(nota);
  }

  if (fat.conta) return el;

  const sit = h('div', { class: 'situacao' });
  sit.style.setProperty('--n', String(n + 1));
  if (r.status === 'ok') {
    sit.classList.add('situacao-ok');
    sit.append(ico('check-circle'), h('div', {}, h('strong', {}, 'Conferido'), h('p', {}, 'A soma das transações bate com o total da fatura.')));
    el.append(sit);
  } else if (r.status === 'divergente') {
    const dif = r.diff_cents ?? 0;
    const mais = dif > 0;
    sit.classList.add('situacao-alerta');
    sit.append(ico('warning'), h('div', {},
      h('strong', {}, `Divergência de ${brl(Math.abs(dif))}`),
      h('p', {}, `As transações somam ${brl(Math.abs(dif))} a ${mais ? 'mais' : 'menos'} que o total da fatura. Revise os lançamentos ou confira o total informado.`)));
    el.append(sit, h('details', {}, h('summary', {}, 'Corrigir o total'), formTotal(fat, ctx)));
  } else {
    sit.append(ico('info'), h('div', {}, h('strong', {}, 'Falta o total para conferir'),
      h('p', {}, 'Esse arquivo não traz o total da fatura. Digite o valor que aparece no app do banco.')));
    el.append(sit, formTotal(fat, ctx));
  }
  return el;
}

function formTotal(fat: Fatura, ctx: Ctx): HTMLFormElement {
  const idCampo = novoId('total');
  const input = h('input', { class: 'entrada', id: idCampo, inputmode: 'decimal', autocomplete: 'off', placeholder: '1.234,56', 'aria-describedby': `${idCampo}-dica` });
  const erro = h('p', { class: 'erro', role: 'alert', hidden: true });
  const botao = h('button', { class: 'btn btn-inverso', type: 'submit' }, 'Conferir');
  const form = h('form', {
    class: 'ledger-form', novalidate: true,
    onsubmit: async (e) => {
      e.preventDefault();
      erro.hidden = true;
      if (!input.value.trim()) { erro.textContent = 'Digite o total que aparece na fatura.'; erro.hidden = false; input.focus(); return; }
      botao.disabled = true;
      try {
        const nova = await api<Fatura>(`/api/faturas/${fat.id}`, { method: 'PATCH', json: { total: input.value } });
        pedirRevelar(fat.id);
        await ctx.recarregar(fat.id);
        toast(nova.status === 'ok' ? 'Conferido. A soma bate com o total.' : 'O total não bate com a soma das transações.', { erro: nova.status !== 'ok' });
      } catch (err) {
        erro.textContent = msgErro(err); erro.hidden = false; botao.disabled = false; input.focus();
      }
    },
  },
    h('label', { for: idCampo }, 'Total da fatura'),
    h('div', { class: 'linha' }, input, botao),
    h('p', { class: 'dica', id: `${idCampo}-dica` }, 'Use vírgula nos centavos. Exemplo: 1.234,56'),
    erro);
  return form;
}

function categorias(res: ResumoFatura): HTMLElement {
  const sec = h('section', { class: 'secao', 'aria-labelledby': 'tit-cats' });
  const cab = h('div', { class: 'secao-cab' }, h('h2', { id: 'tit-cats' }, 'Para onde foi'));
  if (res.anterior) {
    const dif = res.gasto_cents - res.anterior.gasto_cents;
    const texto = dif === 0 ? 'Igual à fatura anterior'
      : `${brl(Math.abs(dif))} a ${dif < 0 ? 'menos' : 'mais'} que na fatura anterior`;
    cab.append(h('p', {}, dif === 0 ? null : ico(dif < 0 ? 'trend-down' : 'trend-up'), texto));
  }
  sec.append(cab);

  if (!res.categorias.length) {
    sec.append(h('p', { class: 'muted' }, 'Nenhum gasto para agrupar nesta fatura.'));
    return sec;
  }
  const max = Math.max(...res.categorias.map((c) => c.total_cents));
  const base = res.categorias.reduce((s, c) => s + c.total_cents, 0) || 1;
  const lista = h('div', { class: 'cats' });
  for (const c of res.categorias) {
    const pct = (c.total_cents / base) * 100;
    const pctTxt = pct < 1 ? '<1%' : `${Math.round(pct)}%`;
    const a = h('a', { class: 'cat', href: `#/transacoes?cat=${encodeURIComponent(c.nome)}`, 'aria-label': `${c.nome}, ${brl(c.total_cents)}, ${pctTxt} do gasto. Ver lançamentos.` },
      h('span', { class: 'cat-nome' }, c.nome, h('small', {}, pctTxt)),
      h('span', { class: 'cat-valor num' }, brl(c.total_cents)),
      h('span', { class: 'cat-barra' }));
    a.querySelector<HTMLElement>('.cat-barra')?.style.setProperty('--w', ((c.total_cents / max) * 100).toFixed(1));
    dica(a, () => ({ titulo: c.nome, texto: `${brl(c.total_cents)}, ${pctTxt} do gasto, ${plural(c.qtd, 'lançamento', 'lançamentos')}` }));
    lista.append(a);
  }
  sec.append(lista);
  return sec;
}

function maiores(res: ResumoFatura, conta: boolean): HTMLElement | null {
  if (!res.maiores.length) return null;
  return h('section', { class: 'secao', 'aria-labelledby': 'tit-maiores' },
    h('h2', { id: 'tit-maiores' }, conta ? 'Maiores saídas' : 'Maiores compras'),
    h('ul', { class: 'maiores' }, res.maiores.map((m) => h('li', { class: 'linha-item' },
      h('span', { class: 'desc' }, m.descricao),
      h('span', { class: 'valor num' }, brl(m.valor_cents)),
      h('span', { class: 'meta' },
        h('span', {}, dm(m.data)),
        m.parcela_total ? h('span', { class: 'etiqueta' }, `${m.parcela_atual}/${m.parcela_total}`) : null,
        h('span', {}, m.categoria))))));
}
