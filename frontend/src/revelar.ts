// A conferência do Resumo "se revela" linha a linha só logo depois de importar ou de informar o total.
// Fica num módulo próprio para quem importa (Faturas, fatura de exemplo) não depender da tela de Resumo.
const CHAVE_REVELAR = 'mare.revelar';

export function consumirRevelar(id: number): boolean {
  try {
    if (sessionStorage.getItem(CHAVE_REVELAR) === String(id)) { sessionStorage.removeItem(CHAVE_REVELAR); return true; }
  } catch { /* sem sessionStorage */ }
  return false;
}

export function pedirRevelar(id: number): void {
  try { sessionStorage.setItem(CHAVE_REVELAR, String(id)); } catch { /* ignora */ }
}
