import { h, ico, novoId } from '../dom.js';
import { api, ApiError } from '../api.js';
import { logoOnda } from '../logo.js';
import type { Usuario } from '../types.js';

type Modo = 'entrar' | 'criar';
interface Opcoes {
  cadastroAberto: boolean;
  /** Servidor com confirmação por e-mail ligada: a conta só nasce depois do código de 6 dígitos. */
  confirmarEmail?: boolean;
  mensagem?: string;
  /** Chamado depois que o servidor aceita as credenciais (o cookie de sessão já foi gravado). */
  aoEntrar(u: Usuario): Promise<void>;
}

interface Pendente { email: string; minutos: number; reenvioSegundos: number }
interface RespostaPendente extends Pendente { pendente: true; codigo_minutos: number; reenvio_segundos: number }
type RespostaCadastro = { usuario: Usuario } | RespostaPendente;

const CAMPO_DO_ERRO: Record<string, 'nome' | 'email' | 'senha'> = {
  nome_invalido: 'nome', email_invalido: 'email', email_em_uso: 'email', senha_fraca: 'senha', credenciais_invalidas: 'senha',
};

// Tela de acesso: entrar ou criar conta. A sessão vive num cookie HttpOnly; aqui a senha só passa pelo formulário e nunca é guardada.
export function telaAcesso({ cadastroAberto, confirmarEmail = false, mensagem = '', aoEntrar }: Opcoes): HTMLElement {
  let modo: Modo = 'entrar';
  let email = '';
  let aviso = mensagem;           // erro vindo de fora (sessão vencida) ou da etapa do código
  let pendente: Pendente | null = null;
  let parar: (() => void) | null = null; // desliga o relógio do reenvio ao sair da etapa do código

  const titulo = h('h1', {});
  const corpo = h('div', { class: 'acesso-corpo' });
  const abas = h('div', { class: 'segmentos acesso-abas', role: 'group', 'aria-label': 'Acesso' });

  function desenharAbas() {
    const aba = (m: Modo, rotulo: string, desligada = false) => h('button', {
      type: 'button', class: 'segmento', 'aria-pressed': String(modo === m), disabled: desligada,
      onclick: () => { if (modo !== m) { modo = m; desenhar(); } },
    }, rotulo);
    abas.replaceChildren(aba('entrar', 'Entrar'), aba('criar', 'Criar conta', !cadastroAberto));
  }

  function desenhar() {
    parar?.(); parar = null;
    if (pendente) {
      abas.hidden = true;
      titulo.textContent = 'Confirme seu e-mail';
      corpo.replaceChildren(etapaDoCodigo(pendente));
      document.title = 'Confirmar e-mail · Maré';
      return;
    }
    abas.hidden = false;
    desenharAbas();
    titulo.textContent = modo === 'entrar' ? 'Entrar na Maré' : 'Criar sua conta';
    corpo.replaceChildren(formulario());
    document.title = `${modo === 'entrar' ? 'Entrar' : 'Criar conta'} · Maré`;
  }

  // Volta ao formulário de cadastro (código bloqueado, vencido ou e-mail errado).
  function voltarAoCadastro(texto = '') {
    pendente = null; aviso = texto; modo = 'criar';
    desenhar();
    if (texto) corpo.querySelector<HTMLInputElement>('input')?.focus();
  }

  function etapaDoCodigo(p: Pendente): HTMLElement {
    const idCodigo = novoId('codigo'), idDica = novoId('dica');
    const campo = h('input', {
      class: 'entrada entrada-codigo', id: idCodigo, name: 'codigo', type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code',
      maxlength: '6', pattern: '[0-9]*', spellcheck: 'false', required: true, 'aria-describedby': idDica,
    });
    campo.addEventListener('input', () => { campo.value = campo.value.replace(/\D/g, '').slice(0, 6); });
    const erro = h('p', { class: 'erro', role: 'alert', hidden: true });
    const ok = h('p', { class: 'dica', role: 'status', hidden: true });
    const botao = h('button', { class: 'btn btn-primario acesso-enviar', type: 'submit' }, 'Confirmar e criar conta');
    const reenviar = h('button', { class: 'btn-texto', type: 'button' }, '');

    const mostrarErro = (texto: string) => {
      ok.hidden = true;
      erro.replaceChildren(ico('warning-circle'), h('span', {}, texto));
      erro.hidden = false;
      campo.focus();
    };

    let falta = p.reenvioSegundos;
    const rotular = () => {
      reenviar.disabled = falta > 0;
      reenviar.textContent = falta > 0 ? `Reenviar código em ${falta} s` : 'Reenviar código';
    };
    const relogio = setInterval(() => { if (falta > 0) { falta--; rotular(); } }, 1000);
    parar = () => clearInterval(relogio);
    rotular();

    reenviar.addEventListener('click', async () => {
      if (falta > 0) return;
      reenviar.disabled = true;
      erro.hidden = true;
      try {
        const r = await api<RespostaPendente>('/api/auth/reenviar', { method: 'POST' });
        falta = r.reenvio_segundos;
        campo.value = '';
        ok.textContent = 'Enviamos um novo código. O anterior deixou de valer.';
        ok.hidden = false;
      } catch (e) {
        if (e instanceof ApiError && e.codigo === 'cadastro_vencido') return voltarAoCadastro('Esse cadastro venceu. Preencha de novo para receber outro código.');
        falta = 15;
        mostrarErro(e instanceof Error ? e.message : 'Não consegui reenviar o código.');
      }
      rotular();
    });

    return h('form', {
      class: 'acesso-form', novalidate: true,
      onsubmit: async (ev) => {
        ev.preventDefault();
        erro.hidden = true;
        if (campo.value.length !== 6) return mostrarErro('Digite os 6 números do código que enviamos.');
        botao.disabled = true;
        botao.textContent = 'Confirmando…';
        try {
          const { usuario } = await api<{ usuario: Usuario }>('/api/auth/confirmar', { method: 'POST', json: { codigo: campo.value } });
          parar?.(); parar = null;
          await aoEntrar(usuario);
        } catch (e) {
          const cod = e instanceof ApiError ? e.codigo : undefined;
          if (cod === 'codigo_bloqueado' || cod === 'cadastro_fechado' || cod === 'email_em_uso') return voltarAoCadastro(e instanceof Error ? e.message : '');
          mostrarErro(e instanceof Error ? e.message : 'Algo deu errado. Tente de novo.');
          botao.disabled = false;
          botao.textContent = 'Confirmar e criar conta';
        }
      },
    },
    h('p', { class: 'acesso-aviso' }, ico('envelope-simple'),
      h('span', {}, `Enviamos um código de 6 números para ${p.email}. Ele vale por ${p.minutos} minutos. Sua conta só é criada depois que você o digitar aqui.`)),
    h('div', { class: 'campo' },
      h('label', { for: idCodigo }, 'Código'), campo,
      h('p', { class: 'dica', id: idDica }, 'Não chegou? Olhe a caixa de spam. Se o e-mail já tiver conta na Maré, enviamos um aviso em vez do código.')),
    erro, ok, botao,
    h('div', { class: 'acesso-passos' }, reenviar,
      h('button', { class: 'btn-texto', type: 'button', onclick: () => voltarAoCadastro() }, 'Usar outro e-mail')));
  }

  function formulario(): HTMLElement {
    const criar = modo === 'criar';
    const idNome = novoId('nome'), idEmail = novoId('email'), idSenha = novoId('senha'), idDica = novoId('dica');

    const nome = h('input', { class: 'entrada', id: idNome, name: 'nome', type: 'text', autocomplete: 'name', maxlength: '100', required: true });
    const campoEmail = h('input', {
      class: 'entrada', id: idEmail, name: 'email', type: 'email', inputmode: 'email', autocomplete: criar ? 'email' : 'username',
      autocapitalize: 'none', spellcheck: 'false', maxlength: '254', required: true,
    });
    campoEmail.value = email;
    campoEmail.addEventListener('input', () => { email = campoEmail.value; });
    const senha = h('input', {
      class: 'entrada', id: idSenha, name: 'senha', type: 'password', autocomplete: criar ? 'new-password' : 'current-password',
      maxlength: '128', required: true, 'aria-describedby': criar ? idDica : undefined,
    });

    const olho = ico('eye');
    const alternar = h('button', {
      type: 'button', class: 'btn-olho', 'aria-pressed': 'false', 'aria-label': 'Mostrar senha',
      onclick: () => {
        const ver = senha.type === 'password';
        senha.type = ver ? 'text' : 'password';
        alternar.setAttribute('aria-pressed', String(ver));
        alternar.setAttribute('aria-label', ver ? 'Ocultar senha' : 'Mostrar senha');
        olho.className = `ico i-${ver ? 'eye-slash' : 'eye'}`;
      },
    }, olho);

    const rotuloCriar = confirmarEmail ? 'Enviar código' : 'Criar conta';
    const textoAviso = aviso; aviso = '';
    const erro = h('p', { class: 'erro', role: 'alert', hidden: !textoAviso }, ico('warning-circle'), h('span', {}, textoAviso));
    const botao = h('button', { class: 'btn btn-primario acesso-enviar', type: 'submit' }, criar ? rotuloCriar : 'Entrar');
    const campos = { nome, email: campoEmail, senha };

    const mostrarErro = (texto: string, foco?: keyof typeof campos) => {
      erro.replaceChildren(ico('warning-circle'), h('span', {}, texto));
      erro.hidden = false;
      if (foco) campos[foco].focus();
    };

    return h('form', {
      class: 'acesso-form', novalidate: true,
      onsubmit: async (ev) => {
        ev.preventDefault();
        erro.hidden = true;
        if (criar && !nome.value.trim()) return mostrarErro('Diga como devemos te chamar.', 'nome');
        if (!campoEmail.value.trim()) return mostrarErro('Digite seu e-mail.', 'email');
        if (!senha.value) return mostrarErro(criar ? 'Crie uma senha.' : 'Digite sua senha.', 'senha');
        botao.disabled = true;
        botao.textContent = criar ? (confirmarEmail ? 'Enviando…' : 'Criando…') : 'Entrando…';
        try {
          const corpoEnvio = criar
            ? { nome: nome.value.trim(), email: campoEmail.value.trim(), senha: senha.value }
            : { email: campoEmail.value.trim(), senha: senha.value };
          const r = await api<RespostaCadastro>(criar ? '/api/auth/cadastro' : '/api/auth/entrar', { method: 'POST', json: corpoEnvio });
          senha.value = '';
          if ('pendente' in r) { // conta ainda não existe: falta o código que foi por e-mail
            pendente = { email: r.email, minutos: r.codigo_minutos, reenvioSegundos: r.reenvio_segundos };
            desenhar();
            queueMicrotask(() => corpo.querySelector<HTMLInputElement>('input')?.focus());
            return;
          }
          await aoEntrar(r.usuario);
        } catch (e) {
          const cod = e instanceof ApiError ? e.codigo : undefined;
          mostrarErro(e instanceof Error ? e.message : 'Algo deu errado. Tente de novo.', (cod && CAMPO_DO_ERRO[cod]) || 'senha');
          botao.disabled = false;
          botao.textContent = criar ? rotuloCriar : 'Entrar';
        }
      },
    },
    criar && h('div', { class: 'campo' }, h('label', { for: idNome }, 'Nome'), nome),
    h('div', { class: 'campo' }, h('label', { for: idEmail }, 'E-mail'), campoEmail),
    h('div', { class: 'campo' },
      h('label', { for: idSenha }, 'Senha'),
      h('div', { class: 'campo-senha' }, senha, alternar),
      criar && h('p', { class: 'dica', id: idDica }, 'Pelo menos 10 caracteres. Uma frase longa funciona melhor que uma palavra com símbolos.')),
    criar && h('p', { class: 'acesso-aviso' }, ico('envelope-simple'),
      h('span', {}, confirmarEmail
        ? 'Vamos enviar um código de 6 números para o seu e-mail. A conta só é criada depois que você digitar esse código.'
        : 'Este servidor ainda não confirma o e-mail: ao criar a conta você já entra.')),
    erro, botao,
    !cadastroAberto && h('p', { class: 'dica' }, 'O cadastro está fechado neste servidor. Peça a quem administra para criar sua conta.'));
  }

  const el = h('section', { class: 'acesso' },
    h('div', { class: 'acesso-marca mare' },
      logoOnda('logo-onda logo-onda-grande'),
      h('p', { class: 'acesso-nome', 'aria-hidden': 'true' }, 'maré'),
      h('p', { class: 'acesso-lema' }, 'Importe a fatura e veja para onde o dinheiro foi.')),
    h('div', { class: 'acesso-painel' }, titulo, abas, corpo));
  desenhar();
  queueMicrotask(() => el.querySelector<HTMLInputElement>('input')?.focus());
  return el;
}
