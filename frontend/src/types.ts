// Formato das respostas da API (app/db.py e app/main.py). Valores em dinheiro sempre em centavos.
export type TipoTransacao = 'compra' | 'encargo' | 'saldo_anterior' | 'estorno' | 'pagamento' | 'entrada' | 'interno';
export type StatusFatura = 'ok' | 'divergente' | 'sem_total';

export interface Transacao {
  id: number;
  data: string;
  descricao: string;
  valor_cents: number;
  tipo: TipoTransacao;
  parcela_atual: number | null;
  parcela_total: number | null;
  categoria: string;
}

export interface Reconciliacao {
  status: StatusFatura;
  compras_cents: number;
  encargos_cents: number;
  saldo_anterior_cents: number;
  estornos_cents: number;
  pagamentos_cents: number;
  entradas_cents: number;
  internos_cents: number;
  soma_cents: number;
  total_cents: number | null;
  diff_cents: number | null;
}

export interface FaturaResumo {
  id: number;
  emissor: string | null;
  vencimento: string | null;
  fechamento: string | null;
  referencia: string;
  total_cents: number | null;
  soma_cents: number;
  diff_cents: number | null;
  status: StatusFatura;
  formato: string;
  conta: boolean;
  arquivo: string;
  avisos: string[];
  n_transacoes: number;
}

export interface Fatura extends Omit<FaturaResumo, 'n_transacoes'> {
  reconciliacao: Reconciliacao;
  transacoes: Transacao[];
  /** Presente quando o arquivo era uma versão mais completa de uma fatura já importada. */
  atualizada?: { novos: number };
}

export interface CategoriaTotal { nome: string; total_cents: number; qtd: number }
export interface MaiorCompra {
  descricao: string; valor_cents: number; data: string; categoria: string;
  parcela_atual: number | null; parcela_total: number | null;
}
export interface ResumoFatura {
  gasto_cents: number;
  anterior: { gasto_cents: number } | null;
  categorias: CategoriaTotal[];
  maiores: MaiorCompra[];
}

export interface ParcelaFutura { descricao: string; emissor: string | null; valor_cents: number; parcela: string }
export interface MesParcelas { mes: string; total_cents: number; itens: ParcelaFutura[] }
export interface ParcelasFuturas { total_cents: number; meses: MesParcelas[] }

export interface TrocaCategoria {
  atualizadas: number;
  chave: string;
  categoria_anterior: string;
  anteriores: { id: number; categoria: string }[];
}

export interface Usuario { nome: string; email: string; email_confirmado: boolean }
export interface Sessao { usuario: Usuario | null; cadastro_aberto: boolean; confirmar_email: boolean }

export interface Estado {
  usuario: Usuario | null;
  faturas: FaturaResumo[];
  faturaId: number | null;
  categorias: string[];
}

export interface Ctx {
  state: Estado;
  readonly params: URLSearchParams;
  navegar(destino: string): void;
  recarregar(novoId?: number | null): Promise<void>;
  escolherFatura(id: number, redesenhar?: boolean): void;
}

export type Tela = (ctx: Ctx) => Promise<HTMLElement> | HTMLElement;
