import { api, ApiError } from './api.js';
import { h, ico } from './dom.js';
import { pedirRevelar } from './revelar.js';
import { toast } from './toast.js';
import type { Ctx, Fatura, FaturaResumo } from './types.js';

// Modo demonstração: uma fatura fictícia (static/exemplo) que passa pelo mesmo caminho de um upload de verdade. Assim a
// pessoa vê a conferência, as categorias e as parcelas antes de ir atrás do arquivo do banco. Ela é reconhecida pelo
// nome do arquivo e pode ser excluída a qualquer momento.
export const ARQUIVO_EXEMPLO = 'fatura-exemplo.ofx';
const CAMINHO_EXEMPLO = `/exemplo/${ARQUIVO_EXEMPLO}`;
const NOME_DO_CARTAO = 'Cartão de exemplo';

const msgErro = (e: unknown): string => (e instanceof Error ? e.message : 'Algo deu errado.');

export const ehExemplo = (f: Pick<FaturaResumo, 'arquivo'>): boolean => f.arquivo === ARQUIVO_EXEMPLO;

export async function carregarExemplo(ctx: Ctx): Promise<void> {
  let res: Response;
  try {
    res = await fetch(CAMINHO_EXEMPLO, { credentials: 'same-origin' });
  } catch {
    throw new Error('Não consegui falar com o servidor. Confira a conexão e tente de novo.');
  }
  if (!res.ok) throw new Error('Não consegui abrir a fatura de exemplo. Tente de novo.');
  const fd = new FormData();
  fd.append('arquivo', new File([await res.blob()], ARQUIVO_EXEMPLO));
  fd.append('cartao', NOME_DO_CARTAO);
  try {
    const f = await api<Fatura>('/api/faturas', { method: 'POST', form: fd });
    pedirRevelar(f.id);
    await ctx.recarregar(f.id);
  } catch (e) {
    if (!(e instanceof ApiError && e.codigo === 'ja_importada')) throw e;
    await ctx.recarregar();  // o exemplo já estava na conta: só abre
    const existente = ctx.state.faturas.find(ehExemplo);
    if (existente) ctx.escolherFatura(existente.id, false);
  }
  ctx.navegar('#/resumo');
  toast('Esta é uma fatura de exemplo, com valores fictícios. Quando quiser, exclua e importe a sua.');
}

/** Aviso no topo das telas enquanto houver uma fatura de exemplo na conta, com o botão para excluí-la. */
export function avisoExemplo(ctx: Ctx): HTMLElement | null {
  const exemplos = ctx.state.faturas.filter(ehExemplo);
  if (!exemplos.length) return null;
  const botao = h('button', {
    class: 'btn btn-secundario', type: 'button',
    onclick: async () => {
      botao.disabled = true;
      try {
        for (const f of exemplos) await api(`/api/faturas/${f.id}`, { method: 'DELETE' });
        await ctx.recarregar();
        toast('Exemplo excluído. Importe a sua fatura quando quiser.');
      } catch (e) {
        toast(msgErro(e), { erro: true });
        botao.disabled = false;
      }
    },
  }, 'Excluir o exemplo');
  return h('div', { class: 'exemplo-aviso', role: 'note' },
    ico('info'),
    h('p', {}, h('strong', {}, 'Fatura de exemplo.'), ' Os valores são fictícios e entram nas contas do app até você excluí-la.'),
    botao);
}
