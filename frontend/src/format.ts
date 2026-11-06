const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

const mesNome = (m: string | undefined): string => MESES[Number(m) - 1] ?? '';

export const brl = (centavos: number | null | undefined): string => BRL.format((centavos || 0) / 100);
export const brlNegativo = (centavos: number): string => `-${brl(Math.abs(centavos))}`;

export function dataBR(iso: string | null | undefined): string {
  if (!iso) return '';
  const [a, m, d] = iso.slice(0, 10).split('-');
  return `${d}/${m}/${a}`;
}
export function dm(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split('-');
  return `${d}/${m}`;
}
export function diaExtenso(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split('-');
  return `${Number(d)} de ${mesNome(m)}`;
}
export function mesLongo(ym: string): string {
  const [a, m] = ym.split('-');
  return `${mesNome(m)} de ${a}`;
}
export function mesCurto(ym: string): string {
  const [a = '', m] = ym.split('-');
  const nome = mesNome(m).slice(0, 3);
  return m === '01' ? `${nome} ${a.slice(2)}` : nome;
}
export const plural = (n: number, um: string, varios: string): string => `${n} ${n === 1 ? um : varios}`;

export function tamanho(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
}

export const semAcento = (s: string): string => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
