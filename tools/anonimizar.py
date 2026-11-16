"""Anonimiza um arquivo de fatura ou extrato (OFX ou CSV) para virar teste público.

    python tools/anonimizar.py ORIGEM DESTINO [--generico] [--sobrescrever]

O que troca: CPF e CNPJ (inteiros ou mascarados), agência e conta, números longos soltos (11 ou 14 dígitos), e-mails,
telefones, o nome de pessoa física que vem antes de um CPF em Pix e transferências, e as tags de identidade do OFX
(ACCTID, BANKID, BRANCHID, FITID...). O que NÃO troca: datas, valores, tipos e o nome de lojas e empresas (CNPJ), porque é
isso que o teste precisa conferir.

Com --generico, também troca o nome de lojas e empresas locais por um nome genérico que cai na MESMA categoria
(RESTAURANTE EXEMPLO 01, AUTO PECAS EXEMPLO 01...) e reduz bancos pequenos a BANCO EXEMPLO, porque o que sobra num
extrato (onde a pessoa compra, a cooperativa, a igreja) revela a cidade e as crenças dela. Marcas conhecidas (categorias
Assinaturas e Compras) e os grandes bancos ficam. As datas e os valores nunca mudam.

O script nunca escreve o resultado se achar algo suspeito sobrando, e nunca imprime o conteúdo original. Ele não
consegue achar um nome de pessoa que apareça sem CPF ao lado: por isso mostra no fim as descrições com Pix ou
transferência, para você conferir com os olhos antes de commitar.

Guarde o arquivo ORIGINAL fora do repositório ou em tests/bancos/_originais/ (que o .gitignore ignora)."""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# O script roda como `python tools/anonimizar.py`, então a raiz do projeto não está no path por padrão.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.categorize import categorizar  # noqa: E402  (só para o --generico escolher um nome da mesma categoria)

# CPF e CNPJ, inteiros ou mascarados (•, *, x): 123.456.789-00, •••.651.653-••, 48.568.213/0002-21
DOC = re.compile(r"[•*xX\d]{2,3}\.[•*xX\d]{3}\.[•*xX\d]{3}(?:/[•*xX\d]{4})?-[•*xX\d]{2}")
DIGITOS_LONGOS = re.compile(r"(?<![\d.,])(?:\d{11}|\d{14})(?![\d.,])")
AGENCIA = re.compile(r"(?i)(\bag[êe]ncia\s*:?\s*)([\dxX\-]+)")
CONTA = re.compile(r"(?i)(\bconta\s*:\s*)([\dxX.\-]+)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TELEFONE = re.compile(r"(?<!\d)(?:\+55\s?)?\(?\d{2}\)?\s?9?\d{4}-\d{4}(?!\d)")
# "<nome> - <documento>": o nome é o pedaço logo depois de um " - " e antes do documento
NOME_ANTES_DO_DOC = re.compile(r"(?<=- )(?P<nome>[^-<>\r\n]+?)(?P<sep> - )(?P<doc>" + DOC.pattern + r")")

OFX_VALORES_DE_TEXTO = re.compile(r"(<(?:MEMO|NAME|PAYEE)>)([^<\r\n]*)")
OFX_IDENTIDADE = re.compile(r"(<(?:ACCTID|BANKID|BRANCHID|ACCTKEY|CHECKNUM|REFNUM)>)([^<\r\n]*)")
OFX_FITID = re.compile(r"(<FITID>)([^<\r\n]*)")
CITA_PIX = re.compile(r"(?i)\b(pix|transfer[êe]ncia|ted|doc)\b")

# <nome> - <documento neutro> - <banco> [(codigo)] [Agência: ... Conta: ...], já depois da limpeza normal
EMPRESA_E_BANCO = re.compile(
    r"(?<=- )(?P<nome>[^-<>\r\n]+?)(?P<s1> - )(?P<doc>00\.000\.000/0000-00|000\.000\.000-00)(?P<s2> - )"
    r"(?P<banco>[^<\r\n]*?)(?P<fim>\s*(?:\(\d{3,4}\))?\s*(?:Ag[êe]ncia[^<\r\n]*)?)(?=$|[<\r\n])", re.M)
BANCOS_MANTIDOS = re.compile(r"(?i)^(bco|banco|nu pagamentos|mercado ?pago|pagseguro|stone|cloudwalk|pay2all|ef[íi]|picpay|"
                             r"inter|c6|santander|bradesco|ita[úu]|caixa)\b")
MARCAS_QUE_FICAM = {"Assinaturas", "Compras"}   # categorias que só saem de uma lista de marcas conhecidas
ROTULO_POR_CATEGORIA = {
    "Alimentação": "RESTAURANTE EXEMPLO", "Mercado": "SUPERMERCADO EXEMPLO", "Transporte": "AUTO PECAS EXEMPLO",
    "Saúde": "FARMACIA EXEMPLO", "Educação": "ESCOLA EXEMPLO", "Lazer": "CINEMA EXEMPLO", "Viagem": "HOTEL EXEMPLO",
    "Casa": "FERRAGENS EXEMPLO", "Contas e serviços": "ENERGIA EXEMPLO",
}
ROTULO_PADRAO = "EMPRESA EXEMPLO"
JA_GENERICO = re.compile(r"[A-ZÇÃÕÁÉÍÓÚ ]+ EXEMPLO \d+")
PLACEHOLDER_EMAIL = "email@exemplo.com"
PLACEHOLDER_TEL = "(00) 00000-0000"


def _zeros(s: str) -> str:
    return re.sub(r"\d", "0", s)


def _doc_neutro(doc: str) -> str:
    return "00.000.000/0000-00" if "/" in doc else "000.000.000-00"


def _doc_e_placeholder(doc: str) -> bool:
    return re.sub(r"[.\-/]", "", doc).strip("0") == ""


class Relatorio:
    def __init__(self) -> None:
        self.contagem: Counter[str] = Counter()
        self.nomes: dict[str, str] = {}
        self.fitids: dict[str, str] = {}
        self.empresas: dict[str, str] = {}
        self.rotulos: Counter[str] = Counter()

    def pessoa(self, nome: str) -> str:
        if re.fullmatch(r"PESSOA \d+", nome.strip()):  # já anonimizado: rodar de novo não pode trocar os números
            return nome.strip()
        chave = re.sub(r"\s+", " ", nome.strip()).casefold()
        if chave not in self.nomes:
            self.nomes[chave] = f"PESSOA {len(self.nomes) + 1:02d}"
        return self.nomes[chave]

    def conta(self, tipo: str, resultado: str) -> str:
        """Registra que algo desse tipo foi trocado e devolve o texto novo (deixa as lambdas do re.sub legíveis)."""
        self.contagem[tipo] += 1
        return resultado

    def empresa_generica(self, nome: str) -> str:
        """Nome genérico que cai na mesma categoria do original (ou o próprio nome, se for uma marca conhecida)."""
        limpo = re.sub(r"\s+", " ", nome.strip())
        if JA_GENERICO.fullmatch(limpo):  # já genérico: rodar de novo não troca os números
            return limpo
        chave = limpo.casefold()
        if chave not in self.empresas:
            categoria = categorizar(limpo, "compra", None, {})
            if categoria in MARCAS_QUE_FICAM:
                self.empresas[chave] = limpo
            else:
                rotulo = ROTULO_POR_CATEGORIA.get(categoria, ROTULO_PADRAO)
                self.rotulos[rotulo] += 1
                self.empresas[chave] = f"{rotulo} {self.rotulos[rotulo]:02d}"
                self.contagem["nomes de empresas"] += 1
        return self.empresas[chave]

    def fitid(self, original: str) -> str:
        if original not in self.fitids:
            self.fitids[original] = f"ANON{len(self.fitids) + 1:05d}"
        return self.fitids[original]


def limpar_texto(texto: str, rel: Relatorio) -> str:
    """Anonimiza um trecho de descrição. Funciona igual em OFX (conteúdo de MEMO) e em CSV (linha inteira)."""

    def nome_e_doc(m: re.Match[str]) -> str:
        doc = m.group("doc")
        rel.contagem["documentos"] += 1
        if "/" in doc:  # CNPJ: o nome é de empresa e fica (é o que a categorização lê)
            return f"{m.group('nome')}{m.group('sep')}{_doc_neutro(doc)}"
        rel.contagem["nomes de pessoas"] += 1
        return f"{rel.pessoa(m.group('nome'))}{m.group('sep')}{_doc_neutro(doc)}"

    t = NOME_ANTES_DO_DOC.sub(nome_e_doc, texto)

    def doc_solto(m: re.Match[str]) -> str:
        if _doc_e_placeholder(m.group(0)):
            return m.group(0)
        rel.contagem["documentos"] += 1
        return _doc_neutro(m.group(0))

    t = DOC.sub(doc_solto, t)
    t = AGENCIA.sub(lambda m: rel.conta("agências e contas", m.group(1) + _zeros(m.group(2))), t)
    t = CONTA.sub(lambda m: rel.conta("agências e contas", m.group(1) + _zeros(m.group(2))), t)
    t = DIGITOS_LONGOS.sub(lambda m: rel.conta("números longos", _zeros(m.group(0))), t)
    t = EMAIL.sub(lambda m: rel.conta("e-mails", PLACEHOLDER_EMAIL), t)
    t = TELEFONE.sub(lambda m: rel.conta("telefones", PLACEHOLDER_TEL), t)
    return t


def generalizar(texto: str, rel: Relatorio) -> str:
    """Modo --generico: troca o nome da empresa e os bancos pequenos (os que entregam a cidade ou a cooperativa)."""

    def troca(m: re.Match[str]) -> str:
        nome = m.group("nome")
        if "/" in m.group("doc"):  # CNPJ: o nome é de empresa; no CPF o nome já virou PESSOA NN
            nome = rel.empresa_generica(nome)
        banco = m.group("banco").strip()
        if banco and not BANCOS_MANTIDOS.match(banco):
            banco = rel.conta("bancos pequenos", "BANCO EXEMPLO")
        return f"{nome}{m.group('s1')}{m.group('doc')}{m.group('s2')}{banco}{m.group('fim')}"

    return EMPRESA_E_BANCO.sub(troca, texto)


def eh_ofx(texto: str) -> bool:
    return "<OFX>" in texto.upper() or "OFXHEADER" in texto.upper()


def anonimizar(texto: str, rel: Relatorio | None = None, generico: bool = False) -> tuple[str, Relatorio]:
    rel = rel or Relatorio()
    if generico:
        base, rel = anonimizar(texto, rel)  # primeiro a limpeza normal; o modo genérico trabalha sobre o texto já neutro
        return generalizar(base, rel), rel
    if eh_ofx(texto):
        t = OFX_VALORES_DE_TEXTO.sub(lambda m: m.group(1) + limpar_texto(m.group(2), rel), texto)
        t = OFX_IDENTIDADE.sub(lambda m: rel.conta("ids de conta", m.group(1) + _zeros(m.group(2))), t)
        t = OFX_FITID.sub(lambda m: m.group(1) + rel.fitid(m.group(2)), t)
        rel.contagem["ids de transação"] = len(rel.fitids)
        return t, rel
    return limpar_texto(texto, rel), rel


def achados(texto: str) -> list[tuple[int, str]]:
    """Linhas (número, tipo) onde ainda parece haver dado pessoal. Não devolve o conteúdo, só onde olhar."""
    ofx = eh_ofx(texto)
    ruins: list[tuple[int, str]] = []
    for n, linha in enumerate(texto.splitlines(), 1):
        if ofx:
            partes = [m.group(2) for m in OFX_VALORES_DE_TEXTO.finditer(linha)]
            partes += [m.group(2) for m in OFX_IDENTIDADE.finditer(linha)]
            alvo = " ".join(partes)
            if not alvo:
                continue
        else:
            alvo = linha
        if any(not _doc_e_placeholder(d) for d in DOC.findall(alvo)):
            ruins.append((n, "CPF/CNPJ"))
        if DIGITOS_LONGOS.search(re.sub(r"0{11,}", "", alvo)):  # zeros em sequência são o que o próprio script escreveu
            ruins.append((n, "número longo"))
        for rx, tipo in ((AGENCIA, "agência"), (CONTA, "conta")):
            if any(re.search(r"[1-9]", m.group(2)) for m in rx.finditer(alvo)):
                ruins.append((n, tipo))
        if any(m.group(0) != PLACEHOLDER_EMAIL for m in EMAIL.finditer(alvo)):
            ruins.append((n, "e-mail"))
        if any(m.group(0) != PLACEHOLDER_TEL for m in TELEFONE.finditer(alvo)):
            ruins.append((n, "telefone"))
    return ruins


def _decodificar(dados: bytes) -> tuple[str, str]:
    cabeca = dados[:400].decode("ascii", "ignore").upper()
    if "CHARSET:1252" in cabeca:
        return dados.decode("cp1252"), "cp1252"
    try:
        return dados.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return dados.decode("cp1252"), "cp1252"


def descricoes_para_conferir(texto: str, limite: int = 40) -> list[str]:
    """Descrições distintas que citam Pix, transferência, TED ou DOC: é onde um nome sem CPF ao lado poderia sobrar."""
    vistas: dict[str, None] = {}
    fontes = [m.group(2) for m in OFX_VALORES_DE_TEXTO.finditer(texto)] if eh_ofx(texto) else texto.splitlines()
    for d in fontes:
        if CITA_PIX.search(d):
            vistas.setdefault(re.sub(r"\s+", " ", d.strip())[:140], None)
    return list(vistas)[:limite]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Anonimiza uma fatura ou extrato (OFX ou CSV) para virar teste público.")
    ap.add_argument("origem", type=Path)
    ap.add_argument("destino", type=Path)
    ap.add_argument("--sobrescrever", action="store_true", help="permite sobrescrever um destino que já existe")
    ap.add_argument("--generico", action="store_true",
                    help="troca nomes de lojas e bancos pequenos por nomes genéricos da mesma categoria "
                         "(recomendado para repositório público)")
    a = ap.parse_args(argv)

    if not a.origem.is_file():
        print(f"Não achei o arquivo de origem: {a.origem}", file=sys.stderr)
        return 2
    if a.destino.resolve() == a.origem.resolve():
        print("O destino não pode ser o próprio arquivo original (ele seria sobrescrito).", file=sys.stderr)
        return 2
    if "_originais" in {p.name for p in a.destino.resolve().parents}:
        print("O destino está em _originais, que é a pasta dos arquivos crus. Escolha outro lugar.", file=sys.stderr)
        return 2
    if re.search(r"\d{6,}", a.destino.name):
        print(f"O nome do destino tem uma sequência longa de números ({a.destino.name}); pode ser o número da sua conta. "
              "Use um nome neutro, como nubank-conta.ofx.", file=sys.stderr)
        return 2
    if a.destino.exists() and not a.sobrescrever:
        print(f"{a.destino} já existe. Use --sobrescrever para trocar.", file=sys.stderr)
        return 2

    texto, codificacao = _decodificar(a.origem.read_bytes())
    novo, rel = anonimizar(texto, generico=a.generico)
    sobras = achados(novo)
    if sobras:
        print("PAREI: ainda parece haver dado pessoal no resultado, então nada foi escrito.", file=sys.stderr)
        for n, tipo in sobras[:30]:
            print(f"  linha {n}: {tipo}", file=sys.stderr)
        return 1

    a.destino.parent.mkdir(parents=True, exist_ok=True)
    a.destino.write_bytes(novo.encode(codificacao))
    print(f"Escrevi {a.destino} ({codificacao}).")
    if rel.contagem:
        print("Trocado: " + ", ".join(f"{v} {k}" for k, v in rel.contagem.items()))
    else:
        print("Nada precisou ser trocado.")
    conferir = descricoes_para_conferir(novo)
    if conferir:
        print("\nConfira se sobrou algum nome de pessoa nestas descrições (Pix, transferência, TED, DOC):")
        for d in conferir:
            print("  -", d)
    print("\nAntes de commitar, abra o arquivo e procure por nomes, apelidos e números que ainda façam sentido para alguém. "
          "O repositório é público.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
