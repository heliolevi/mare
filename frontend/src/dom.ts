// Construção de DOM segura: tudo entra como texto (nada de innerHTML), porque descrições vêm de arquivos de terceiros.
export type Filho = Node | string | number | null | undefined | false | readonly Filho[];
type Prop = string | number | boolean | null | undefined | ((ev: Event) => unknown);
export type Props = Record<string, Prop>;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, props: Props | null = {}, ...filhos: Filho[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props ?? {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = String(v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
  anexar(el, filhos);
  return el;
}

export function anexar<T extends Element>(el: T, filhos: readonly Filho[]): T {
  for (const f of filhos) {
    if (f == null || f === false) continue;
    if (Array.isArray(f)) anexar(el, f);
    else el.append(f instanceof Node ? f : document.createTextNode(String(f)));
  }
  return el;
}

// Ícones Phosphor (regular) aplicados por máscara; as classes .i-nome ficam em app.css.
export const ico = (nome: string, extra = ''): HTMLSpanElement => h('span', { class: `ico i-${nome} ${extra}`.trim(), 'aria-hidden': 'true' });

let _id = 0;
export const novoId = (prefixo = 'id'): string => `${prefixo}-${++_id}`;
