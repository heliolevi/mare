import { h, ico, novoId } from '../dom.js';
import { api, ApiError } from '../api.js';
import { logoOnda } from '../logo.js';
import type { Usuario } from '../types.js';

type Modo = 'entrar' | 'criar';
interface Opcoes {
  cadastroAberto: boolean;
  mensagem?: string;
  /** Chamado depois que o servidor aceita as credenciais (o cookie de sessão já foi gravado). */
  aoEntrar(u: Usuario): Promise<void>;
}

const CAMPO_DO_ERRO: Record<string, 'nome' | 'email' | 'senha'> = {
  nome_invalido: 'nome', email_invalido: 'email', email_em_uso: 'email', senha_fraca: 'senha', credenciais_invalidas: 'senha',
};

// Tela de acesso: entrar ou criar conta. A sessão vive num cookie HttpOnly; aqui a senha só passa pelo formulário e nunca é guardada.
export function telaAcesso({ cadastroAberto, mensagem = '', aoEntrar }: Opcoes): HTMLElement {
  let modo: Modo = 'entrar';
  let email = '';

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
    desenharAbas();
    titulo.textContent = modo === 'entrar' ? 'Entrar na Maré' : 'Criar sua conta';
    corpo.replaceChildren(formulario());
    document.title = `${modo === 'entrar' ? 'Entrar' : 'Criar conta'} · Maré`;
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

    const erro = h('p', { class: 'erro', role: 'alert', hidden: !mensagem || criar }, ico('warning-circle'), h('span', {}, mensagem));
    const botao = h('button', { class: 'btn btn-primario acesso-enviar', type: 'submit' }, criar ? 'Criar conta' : 'Entrar');
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
        botao.textContent = criar ? 'Criando…' : 'Entrando…';
        try {
          const corpoEnvio = criar
            ? { nome: nome.value.trim(), email: campoEmail.value.trim(), senha: senha.value }
            : { email: campoEmail.value.trim(), senha: senha.value };
          const { usuario } = await api<{ usuario: Usuario }>(criar ? '/api/auth/cadastro' : '/api/auth/entrar', { method: 'POST', json: corpoEnvio });
          senha.value = '';
          await aoEntrar(usuario);
        } catch (e) {
          const cod = e instanceof ApiError ? e.codigo : undefined;
          mostrarErro(e instanceof Error ? e.message : 'Algo deu errado. Tente de novo.', (cod && CAMPO_DO_ERRO[cod]) || 'senha');
          botao.disabled = false;
          botao.textContent = criar ? 'Criar conta' : 'Entrar';
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
      h('span', {}, 'Em breve vamos enviar um e-mail para confirmar a criação da conta. Por enquanto, ao criar a conta você já entra.')),
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
