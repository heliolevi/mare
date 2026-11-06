import { h, ico, novoId } from '../dom.js';
import { api } from '../api.js';
import { brl, dataBR, plural, tamanho } from '../format.js';
import { toast } from '../toast.js';
import { confirmar, rotuloFatura, selo } from '../componentes.js';
import { pedirRevelar } from './resumo.js';
import type { Ctx, Fatura, FaturaResumo } from '../types.js';

const msgErro = (e: unknown): string => (e instanceof Error ? e.message : 'Algo deu errado.');
const EXTENSOES = ['.ofx', '.qfx', '.csv', '.txt'];
const LIMITE_MB = 5;

export default async function faturas(ctx: Ctx): Promise<HTMLElement> {
  const { state } = ctx;
  return h('div', {},
    h('div', { class: 'topo' }, h('div', { class: 'topo-texto' }, h('h1', {}, 'Faturas'),
      h('p', {}, 'Importe o arquivo da fatura. O app soma os lançamentos e confere com o total.'))),
    formImportar(ctx),
    listaFaturas(ctx, state.faturas));
}

function formImportar(ctx: Ctx): HTMLFormElement {
  let arquivo: File | null = null;
  const idArq = novoId('arquivo');
  const entrada = h('input', { type: 'file', id: idArq, accept: '.ofx,.qfx,.csv,.txt,text/csv,application/x-ofx', 'aria-describedby': 'drop-dica' });
  const titulo = h('strong', {}, 'Escolher o arquivo da fatura');
  const dicaDrop = h('span', { id: 'drop-dica' }, 'OFX ou CSV, até 5 MB. Também dá para arrastar para cá.');
  const drop = h('label', { class: 'drop', for: idArq }, ico('upload-simple', 'ico-xl'), titulo, dicaDrop, entrada);

  const erro = h('p', { class: 'erro', role: 'alert', hidden: true });
  const botao = h('button', { class: 'btn btn-primario', type: 'submit', disabled: true }, 'Importar');
  const estado = h('span', { class: 'dica', 'aria-live': 'polite' });

  const idTotal = novoId('total'); const idVenc = novoId('venc'); const idCartao = novoId('cartao');
  const total = h('input', { class: 'entrada', id: idTotal, inputmode: 'decimal', autocomplete: 'off', placeholder: '1.234,56', 'aria-describedby': `${idTotal}-d` });
  const venc = h('input', { class: 'entrada', id: idVenc, type: 'date', 'aria-describedby': `${idVenc}-d` });
  const cartao = h('input', { class: 'entrada', id: idCartao, autocomplete: 'off', maxlength: '60', placeholder: 'Nubank, Inter, C6...' });

  function mostrarErro(msg: string) { erro.replaceChildren(ico('warning-circle'), h('span', {}, msg)); erro.hidden = false; }
  function escolher(f: File | null | undefined) {
    erro.hidden = true;
    if (!f) return;
    const nome = f.name.toLowerCase();
    if (nome.endsWith('.pdf')) { arquivo = null; botao.disabled = true; mostrarErro('PDF não é aceito. Baixe a fatura em OFX ou CSV no app ou no site do banco.'); return; }
    if (f.size > LIMITE_MB * 1024 * 1024) { arquivo = null; botao.disabled = true; mostrarErro(`O arquivo tem ${tamanho(f.size)} e o limite é ${LIMITE_MB} MB. Exporte só o período que precisa.`); return; }
    if (f.size === 0) { arquivo = null; botao.disabled = true; mostrarErro('O arquivo está vazio. Baixe de novo no app do banco.'); return; }
    if (!EXTENSOES.some((e) => nome.endsWith(e))) { arquivo = null; botao.disabled = true; mostrarErro('Esse tipo de arquivo não é aceito. Envie um OFX ou CSV.'); return; }
    arquivo = f;
    titulo.textContent = f.name;
    dicaDrop.textContent = `${tamanho(f.size)}. Toque para trocar o arquivo.`;
    botao.disabled = false;
  }
  entrada.addEventListener('change', () => escolher(entrada.files?.[0]));
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('arrastando'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove('arrastando')));
  drop.addEventListener('drop', (e) => { e.preventDefault(); escolher((e as DragEvent).dataTransfer?.files[0]); });
  // Soltar um arquivo fora da área faria o navegador abrir o arquivo e sair do app.
  const evitarAbrir = (e: Event) => e.preventDefault();
  window.addEventListener('dragover', evitarAbrir);
  window.addEventListener('drop', evitarAbrir);
  window.addEventListener('hashchange', () => { window.removeEventListener('dragover', evitarAbrir); window.removeEventListener('drop', evitarAbrir); }, { once: true });

  const form = h('form', {
    class: 'importar', novalidate: true,
    onsubmit: async (e) => {
      e.preventDefault();
      if (!arquivo) return;
      erro.hidden = true;
      botao.disabled = true;
      botao.replaceChildren(ico('circle-notch', 'girar'), 'Lendo o arquivo');
      botao.setAttribute('aria-busy', 'true');
      const fd = new FormData();
      fd.append('arquivo', arquivo);
      if (total.value.trim()) fd.append('total', total.value.trim());
      if (venc.value) fd.append('vencimento', venc.value);
      if (cartao.value.trim()) fd.append('cartao', cartao.value.trim());
      try {
        const f = await api<Fatura>('/api/faturas', { method: 'POST', form: fd });
        pedirRevelar(f.id);
        await ctx.recarregar(f.id);
        // 200 + atualizada: o arquivo era uma versão mais completa de uma fatura já importada; só os lançamentos novos entraram.
        const n = f.atualizada
          ? `Fatura atualizada: ${plural(f.atualizada.novos, 'lançamento novo', 'lançamentos novos')}.`
          : plural(f.transacoes.length, 'lançamento importado', 'lançamentos importados');
        toast(f.status === 'divergente' ? `${n} A soma não bate com o total.` : n, { erro: f.status === 'divergente' });
        ctx.navegar('#/resumo');
      } catch (err) {
        mostrarErro(msgErro(err));
        botao.disabled = false;
      } finally {
        botao.replaceChildren('Importar');
        botao.removeAttribute('aria-busy');
      }
    },
  },
    h('h2', {}, 'Importar fatura'),
    drop,
    erro,
    h('details', {},
      h('summary', {}, 'Informar total, vencimento ou nome do cartão (opcional)'),
      h('div', { class: 'opcionais' },
        h('div', { class: 'campo' }, h('label', { for: idTotal }, 'Total da fatura'), total,
          h('p', { class: 'dica', id: `${idTotal}-d` }, 'Sem o total o app não consegue conferir a soma. Arquivos OFX costumam trazer.')),
        h('div', { class: 'campo' }, h('label', { for: idVenc }, 'Vencimento'), venc,
          h('p', { class: 'dica', id: `${idVenc}-d` }, 'Usado para projetar as parcelas nos meses certos.')),
        h('div', { class: 'campo largo' }, h('label', { for: idCartao }, 'Nome do cartão'), cartao))),
    h('div', { class: 'acoes' }, botao, estado),
    h('details', {},
      h('summary', {}, 'Como baixar o arquivo no meu banco'),
      h('div', { class: 'ajuda' },
        h('ul', {},
          h('li', {}, 'No app ou no site do banco, abra a fatura do cartão e procure Exportar ou Baixar fatura.'),
          h('li', {}, 'Prefira OFX, que já traz o total da fatura. Se não existir, use CSV.'),
          h('li', {}, 'O C6 Bank, por exemplo, oferece CSV no app, em Cartões, Baixar fatura.'),
          h('li', {}, 'PDF e planilhas do Excel não são aceitos.')),
        h('p', {}, 'O arquivo é lido no servidor do app e descartado. Só os lançamentos ficam salvos, e nada é enviado a serviços externos.'))));
  return form;
}

function listaFaturas(ctx: Ctx, lista: FaturaResumo[]): HTMLElement {
  const sec = h('section', { class: 'secao', 'aria-labelledby': 'tit-lista' }, h('h2', { id: 'tit-lista' }, 'Faturas importadas'));
  if (!lista.length) {
    sec.append(h('p', { class: 'muted' }, 'Nada importado ainda. Quando você importar a primeira, ela aparece aqui.'));
    return sec;
  }
  sec.append(h('ul', { class: 'lista-faturas' }, lista.map((f) => {
    const total = f.total_cents ?? f.soma_cents;
    return h('li', { class: 'fatura-item' },
      h('a', {
        class: 'fatura-link', href: '#/resumo',
        onclick: () => ctx.escolherFatura(f.id, false),
        'aria-label': `Abrir ${rotuloFatura(f)}, ${brl(total)}`,
      },
        h('span', { class: 'nome' }, rotuloFatura(f)),
        h('span', { class: 'total num' }, brl(total)),
        h('span', { class: 'sub' }, selo(f), h('span', {}, plural(f.n_transacoes, 'lançamento', 'lançamentos')), h('span', {}, f.formato.toUpperCase()))),
      h('button', {
        class: 'btn btn-icone', type: 'button', 'aria-label': `Excluir a fatura ${rotuloFatura(f)}`,
        onclick: async () => {
          const ok = await confirmar({ titulo: 'Excluir esta fatura?', texto: `Isso remove os ${plural(f.n_transacoes, 'lançamento importado', 'lançamentos importados')} de ${rotuloFatura(f)}. Não dá para desfazer.`, ok: 'Excluir fatura' });
          if (!ok) return;
          try {
            await api(`/api/faturas/${f.id}`, { method: 'DELETE' });
            await ctx.recarregar();
            toast('Fatura excluída.');
          } catch (err) { toast(msgErro(err), { erro: true }); }
        },
      }, ico('trash')));
  })));
  return sec;
}
