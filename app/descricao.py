"""Apresentação da descrição de um lançamento.

O extrato do banco chega com a string crua: "Transferência enviada pelo Pix - FULANO - •••.123.456-•• - BCO X S.A. (0001)
Agência: 1 Conta: 2-3". Ela continua guardada inteira no banco (é parte da identidade do arquivo e da chave das regras),
mas nunca sai da API desse jeito: CPF, CNPJ, agência e conta de terceiros não têm motivo para aparecer na tela.

apresentar() devolve o que a interface mostra: um título (quem recebeu ou onde foi a compra) e um detalhe curto
(o tipo da operação e o banco)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .norm import norm_text

# CPF e CNPJ, inteiros ou mascarados (•, *, x): 123.456.789-00, •••.651.653-••, 48.568.213/0002-21
_DOC = re.compile(r"[•*xX\d]{2,3}\.[•*xX\d]{3}\.[•*xX\d]{3}(?:/[•*xX\d]{4})?-[•*xX\d]{2}")
_DOC_SEGMENTO = re.compile(r"^[•*xX\d][•*xX\d.\-/ ]{7,}$")
_DIGITOS_LONGOS = re.compile(r"\b\d{11}\b|\b\d{14}\b")  # CPF/CNPJ sem pontuação
_AGENCIA = re.compile(r"(?i)\bag[êe]ncia\s*:?\s*[\dxX\-]+")
_CONTA = re.compile(r"(?i)\bconta\s*:\s*[\dxX.\-]+")
_COD_BANCO = re.compile(r"\(\d{3,4}\)")

# Abertura da descrição -> rótulo curto do tipo. A ordem importa: o mais específico primeiro.
_TIPOS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)^transfer[êe]ncia enviada pelo pix$"), "Pix enviado"),
    (re.compile(r"(?i)^transfer[êe]ncia recebida pelo pix$"), "Pix recebido"),
    (re.compile(r"(?i)^pix enviado$"), "Pix enviado"),
    (re.compile(r"(?i)^pix recebido$"), "Pix recebido"),
    (re.compile(r"(?i)^transfer[êe]ncia enviada$"), "Transferência enviada"),
    (re.compile(r"(?i)^transfer[êe]ncia recebida$"), "Transferência recebida"),
    (re.compile(r"(?i)^(ted|doc) (enviad[ao]|recebid[ao])$"), ""),  # rótulo = o próprio texto
    (re.compile(r"(?i)^compra no d[ée]bito via (.+)$"), "Débito via {0}"),
    (re.compile(r"(?i)^compra no d[ée]bito$"), "Débito"),
    (re.compile(r"(?i)^compra no cr[ée]dito$"), "Crédito"),
    (re.compile(r"(?i)^pagamento de boleto( efetuado)?$"), "Boleto"),
    (re.compile(r"(?i)^valor adicionado na conta por cart[ãa]o de cr[ée]dito$"), "Crédito na conta"),
    (re.compile(r"(?i)^(dep[óo]sito|saque|estorno|reembolso)( .*)?$"), ""),
]
_TRANSFERENCIA = re.compile(r"(?i)\b(pix|transfer[êe]ncia|ted|doc)\b")

_BANCOS = [
    (r"\bbco do brasil|banco do brasil\b", "Banco do Brasil"), (r"\bbradesco\b", "Bradesco"), (r"\bita[uú]\b", "Itaú"),
    (r"\bcaixa econ", "Caixa"), (r"\bsantander\b", "Santander"), (r"\bnu pagamentos|nubank\b", "Nubank"),
    (r"\binter\b", "Inter"), (r"\bc6\b", "C6 Bank"), (r"\bpicpay\b", "PicPay"), (r"\bmercado ?pago\b", "Mercado Pago"),
    (r"\bpagseguro|pagbank\b", "PagBank"), (r"\bstone\b", "Stone"), (r"\bsicoob\b", "Sicoob"), (r"\bsicredi\b", "Sicredi"),
    (r"\bbanrisul\b", "Banrisul"), (r"\bbtg\b", "BTG"), (r"\bneon\b", "Neon"), (r"\bpan\b", "Banco Pan"),
]
_BANCOS_RX = [(re.compile(rx, re.I), nome) for rx, nome in _BANCOS]

_MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "em", "na", "no", "para", "com", "a", "o"}
_SIGLAS = {"sa", "s/a", "ltda", "me", "mei", "eireli", "epp", "ip", "cia", "s.a.", "ltda."}


@dataclass(frozen=True)
class Apresentacao:
    titulo: str
    detalhe: str | None
    transferencia: bool      # Pix/TED/DOC entre contas
    pessoa: bool             # a outra ponta tem CPF (pessoa física), não CNPJ


def sanitizar(texto: str) -> str:
    """Tira CPF, CNPJ, agência, conta e o código do banco; arruma os separadores que sobram."""
    t = _DOC.sub(" ", texto or "")
    t = _DIGITOS_LONGOS.sub(" ", t)
    t = _AGENCIA.sub(" ", t)
    t = _CONTA.sub(" ", t)
    t = _COD_BANCO.sub(" ", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(\s*-\s*){2,}", " - ", t)
    return t.strip(" -")


def _capitalizar(nome: str) -> str:
    """'DHANIEL LYVIO DO NASCIMENTO' -> 'Dhaniel Lyvio do Nascimento'. Texto que já tem minúsculas fica como está
    (a pessoa ou a loja escreveu assim: 'iFood')."""
    if any(ch.islower() for ch in nome):
        return nome
    saida = []
    for i, palavra in enumerate(nome.split()):
        p = palavra.lower()
        if p in _SIGLAS:
            saida.append(palavra.upper().rstrip("."))
        elif i > 0 and p in _MINUSCULAS:
            saida.append(p)
        else:
            saida.append("-".join(parte[:1].upper() + parte[1:] for parte in p.split("-")))
    return " ".join(saida)


def _banco(segmentos: list[str]) -> str | None:
    bruto = sanitizar(" ".join(segmentos))
    if not bruto:
        return None
    for rx, nome in _BANCOS_RX:
        if rx.search(bruto):
            return nome
    limpo = re.sub(r"(?i)\b(bco|banco)\b", "Banco", bruto)
    # Sufixos societários e de instituição de pagamento não ajudam a reconhecer o banco: "Efí S.A. IP" -> "Efí"
    sufixo = re.compile(r"(?i)[\s\-]+(s\.?\s?a\.?|s/a|ltda\.?|ip|instituicao de pagamento|instituição de pagamento)\s*$")
    while (novo := sufixo.sub("", limpo)) != limpo:
        limpo = novo
    return _capitalizar(limpo.strip(" -"))[:40] or None


def _tipo(abertura: str) -> str | None:
    for rx, rotulo in _TIPOS:
        m = rx.match(abertura.strip())
        if m:
            if not rotulo:
                return abertura.strip()[:1].upper() + abertura.strip()[1:].lower()
            return rotulo.format(*(g.strip() for g in m.groups() if g))
    return None


def apresentar(descricao: str) -> Apresentacao:
    original = (descricao or "").strip()
    segmentos = [s.strip() for s in original.split(" - ")]
    tipo = _tipo(segmentos[0]) if len(segmentos) >= 2 else None
    if tipo is None:
        titulo = sanitizar(original) or original
        return Apresentacao(titulo=titulo, detalhe=None, transferencia=bool(_TRANSFERENCIA.search(original)), pessoa=False)

    resto = segmentos[1:]
    # O documento separa "quem" (antes) de "qual banco" (depois). Sem documento, o primeiro pedaço é o nome.
    idx_doc = next((i for i, s in enumerate(resto) if _DOC_SEGMENTO.match(s) or _DOC.search(s)), None)
    if idx_doc is None:
        nome_partes, banco_partes, doc = resto[:1], resto[1:], ""
    else:
        nome_partes, banco_partes, doc = resto[:idx_doc], resto[idx_doc + 1:], resto[idx_doc]
    nome = sanitizar(" - ".join(nome_partes)) or sanitizar(" - ".join(resto)) or tipo
    banco = _banco(banco_partes) if banco_partes else None
    if banco and norm_text(banco) == norm_text(_capitalizar(nome)):
        banco = None  # a empresa é o próprio banco do recebedor (comum em maquininhas): não repete
    transferencia = bool(_TRANSFERENCIA.search(segmentos[0]))
    pessoa = bool(doc) and "/" not in doc  # CNPJ tem barra; CPF não
    detalhe = f"{tipo} · {banco}" if banco else tipo
    return Apresentacao(titulo=_capitalizar(nome)[:120], detalhe=detalhe[:80], transferencia=transferencia, pessoa=pessoa)


def texto_para_regras(descricao: str) -> str:
    """Texto usado pelas palavras-chave da categorização: só o nome de quem recebeu, sem o banco (um banco chamado
    'Mercado Pago' não pode transformar um Pix em compra de mercado)."""
    a = apresentar(descricao)
    return norm_text(a.titulo)
