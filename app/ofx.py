"""Leitor de OFX tolerante. Os bancos brasileiros exportam OFX 1.x (SGML, tags folha sem fechamento, cp1252)."""
from __future__ import annotations

import hashlib
import html
import re

from .models import RawStatement, RawTx
from .norm import limpar_texto, parse_date, parse_money_cents

_BANCOS = [
    ("nubank", "Nubank"), ("nu pagamentos", "Nubank"), ("inter", "Inter"), ("c6", "C6 Bank"),
    ("itau", "Itaú"), ("bradesco", "Bradesco"), ("santander", "Santander"), ("banco do brasil", "Banco do Brasil"),
    ("caixa", "Caixa"), ("xp", "XP"), ("picpay", "PicPay"), ("mercado pago", "Mercado Pago"), ("neon", "Neon"),
    ("original", "Original"), ("sicredi", "Sicredi"), ("sicoob", "Sicoob"), ("btg", "BTG Pactual"),
    ("safra", "Safra"), ("pan", "Banco Pan"),
]


def adivinhar_emissor(*textos: str | None) -> str | None:
    from .norm import norm_text
    junto = " ".join(re.sub(r"[^a-z0-9]+", " ", norm_text(t)) for t in textos if t)
    for chave, nome in _BANCOS:
        if re.search(rf"\b{re.escape(chave)}\b", junto):
            return nome
    return None


def decodificar(data: bytes) -> str:
    cab = data[:800].decode("ascii", "ignore")
    enc = None
    if m := re.search(r"CHARSET:\s*(\w+)", cab, re.I):
        enc = {"1252": "cp1252", "UNICODE": "utf-8", "UTF-8": "utf-8", "8859-1": "latin-1"}.get(m[1].upper())
    if re.search(r"encoding\s*[=:]\s*[\"']?utf-8", cab, re.I):
        enc = "utf-8"
    for e in ([enc] if enc else []) + ["utf-8-sig", "cp1252"]:
        try:
            return data.decode(e)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1")


def _tag(bloco: str, nome: str) -> str | None:
    m = re.search(rf"<{nome}>\s*([^<\r\n]*)", bloco, re.I)
    return html.unescape(m[1].strip()) if m and m[1].strip() else None


def ler_ofx(data: bytes, nome_arquivo: str = "") -> RawStatement:
    texto = decodificar(data)
    i = re.search(r"<OFX", texto, re.I)
    if not i:
        raise ValueError("Não encontrei o início do OFX (tag <OFX>).")
    corpo = texto[i.start():]
    avisos: list[str] = []

    if re.search(r"<CCSTMTRS|<CREDITCARDMSGSRSV1", corpo, re.I):
        tipo_conta = "cartao"
    elif re.search(r"<STMTRS|<BANKMSGSRSV1", corpo, re.I):
        tipo_conta = "conta"
    else:
        tipo_conta = "?"

    blocos = re.findall(
        r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>|\Z)", corpo, re.I | re.S
    )
    if not blocos:
        raise ValueError("O OFX não tem nenhuma transação.")

    inicio = parse_date(_tag(corpo, "DTSTART") or "")
    fim = parse_date(_tag(corpo, "DTEND") or "")

    txs: list[RawTx] = []
    ignoradas = 0
    for b in blocos:
        valor = parse_money_cents(_tag(b, "TRNAMT"))
        data_t = parse_date(_tag(b, "DTPOSTED") or "", fim)
        nome, memo = _tag(b, "NAME"), _tag(b, "MEMO")
        desc = memo or nome or ""
        if memo and nome and nome.lower() not in memo.lower() and len(nome) > 3:
            desc = f"{nome} {memo}"
        if valor is None or valor == 0 or data_t is None or not desc:
            ignoradas += 1
            continue
        desc = limpar_texto(desc)
        if not desc:
            ignoradas += 1
            continue
        txs.append(RawTx(data=data_t, descricao=desc, bruto_cents=valor, fitid=limpar_texto(_tag(b, "FITID"), 64) or None))
    if ignoradas:
        avisos.append(f"{ignoradas} lançamento(s) sem data, valor ou descrição foram ignorados.")
    if not txs:
        raise ValueError("Nenhuma transação válida no OFX.")

    saldo = None
    if m := re.search(r"<LEDGERBAL>.*?<BALAMT>\s*([^<\r\n]*)", corpo, re.I | re.S):
        saldo = parse_money_cents(m[1])
    total = abs(saldo) if saldo else None

    org = _tag(corpo, "ORG")
    emissor = adivinhar_emissor(org, nome_arquivo) or (limpar_texto(org, 40).title() if org and len(org) < 40 else None)
    # Número da conta/cartão entra só como hash: serve para separar cartões sem nome e nunca é gravado em claro.
    partes = [tipo_conta, org or "", _tag(corpo, "FID") or "", _tag(corpo, "BANKID") or "", _tag(corpo, "ACCTID") or ""]
    origem = "ofx:" + hashlib.sha256("|".join(partes).encode()).hexdigest()[:16] if any(partes[1:]) else None
    return RawStatement(formato="ofx", txs=txs, emissor=emissor, total_cents=None if tipo_conta == "conta" else total,
                        inicio=inicio, fim=fim, avisos=avisos, conta=tipo_conta == "conta", origem=origem)
