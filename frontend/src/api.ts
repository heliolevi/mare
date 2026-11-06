// A sessão é um cookie HttpOnly: o JavaScript do app nunca vê nem guarda o token (nada de localStorage).
export class ApiError extends Error {
  constructor(public status: number, public codigo: string | undefined, mensagem: string) {
    super(mensagem);
  }
}

interface Opcoes { method?: string; json?: unknown; form?: FormData }
interface CorpoErro { detail?: { codigo?: string; mensagem?: string } }

// O tipo T é uma promessa sobre o formato da resposta (ver types.ts), não é validado em tempo de execução.
export async function api<T = unknown>(caminho: string, { method = 'GET', json, form }: Opcoes = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  else if (form) body = form;

  let res: Response;
  try {
    // Sem prazo, um servidor travado deixaria a tela esperando para sempre. Envio de arquivo ganha mais tempo.
    res = await fetch(caminho, { method, headers, body, credentials: 'same-origin', signal: AbortSignal.timeout(form ? 90_000 : 30_000) });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      throw new ApiError(0, 'timeout', 'O servidor demorou demais para responder. Tente de novo.');
    }
    throw new ApiError(0, 'offline', 'Não consegui falar com o servidor. Confira a conexão e tente de novo.');
  }
  if (res.status === 204) return null as T;
  const dados = (await res.json().catch(() => null)) as (CorpoErro & T) | null;
  if (!res.ok) {
    const d = dados?.detail;
    // 401 fora das rotas de login significa sessão vencida: volta para a tela de entrada.
    if (res.status === 401 && !caminho.startsWith('/api/auth/')) window.dispatchEvent(new Event('auth-required'));
    const padrao = res.status === 413 ? 'O arquivo é grande demais.' : 'Algo deu errado. Tente de novo.';
    throw new ApiError(res.status, d?.codigo, d?.mensagem || padrao);
  }
  if (dados === null) throw new ApiError(res.status, 'resposta_invalida', 'O servidor respondeu algo inesperado. Tente de novo.');
  return dados as T;
}
