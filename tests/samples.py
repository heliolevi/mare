"""Arquivos de exemplo (fictícios) no formato que os bancos brasileiros usam."""

TOTAL_CENTS = 73679  # 736,79

_TXS = [
    ("20261005120000[-3:BRT]", "-45.90", "a01", "Padaria São João"),
    ("20261007120000[-3:BRT]", "-23.50", "a02", "Uber *Trip"),
    ("20261009120000[-3:BRT]", "-99.90", "a03", "Mercado Livre Parcela 3/10"),
    ("20261012120000[-3:BRT]", "-55.90", "a04", "Netflix.com"),
    ("20261015120000[-3:BRT]", "-312.47", "a05", "Supermercado Mateus"),
    ("20261020120000[-3:BRT]", "-78.30", "a06", "Farmácia Pague Menos"),
    ("20261022120000[-3:BRT]", "33.30", "a07", "Estorno Mercado Livre"),
    ("20261025120000[-3:BRT]", "1500.00", "a08", "Pagamento recebido"),
    ("20261028120000[-3:BRT]", "-150.00", "a09", "Magalu 02/06"),
    ("20261101120000[-3:BRT]", "-4.12", "a10", "IOF compra internacional"),
]


def ofx_cartao(*, invertido: bool = False, saldo: str | None = "-736.79", sem_fechamento: bool = False) -> bytes:
    """OFX 1.x SGML (tags sem fechamento), cp1252, como os bancos exportam."""
    linhas = [
        "OFXHEADER:100", "DATA:OFXSGML", "VERSION:102", "SECURITY:NONE", "ENCODING:USASCII", "CHARSET:1252",
        "COMPRESSION:NONE", "OLDFILEUID:NONE", "NEWFILEUID:NONE", "",
        "<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20261102120000"
        "<LANGUAGE>POR<FI><ORG>NU PAGAMENTOS S.A.<FID>260</FI></SONRS></SIGNONMSGSRSV1>",
        "<CREDITCARDMSGSRSV1><CCSTMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS><CCSTMTRS><CURDEF>BRL",
        "<CCACCTFROM><ACCTID>0000</CCACCTFROM><BANKTRANLIST><DTSTART>20261003<DTEND>20261102",
    ]
    for dt, v, fit, memo in _TXS:
        if invertido:
            v = v[1:] if v.startswith("-") else "-" + v
        tp = "CREDIT" if not v.startswith("-") else "DEBIT"
        linhas.append(f"<STMTTRN><TRNTYPE>{tp}<DTPOSTED>{dt}<TRNAMT>{v}<FITID>{fit}<MEMO>{memo}</STMTTRN>")
    linhas.append("</BANKTRANLIST>")
    if saldo:
        linhas.append(f"<LEDGERBAL><BALAMT>{saldo}<DTASOF>20261102</LEDGERBAL>")
    linhas.append("</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>")
    return "\n".join(linhas).encode("cp1252")


def csv_nubank(com_pagamento: bool = True) -> bytes:
    """date,category,title,amount (compras positivas, pagamento negativo)."""
    linhas = [
        "date,category,title,amount",
        "2026-10-05,restaurante,Padaria Sao Joao,45.90",
        "2026-10-07,transporte,Uber *Trip,23.50",
        "2026-10-09,casa,Mercado Livre - Parcela 3/10,99.90",
        "2026-10-12,serviços,Netflix.com,55.90",
        "2026-10-15,supermercado,Supermercado Mateus,312.47",
        "2026-10-20,saúde,Farmacia Pague Menos,78.30",
        "2026-10-22,,Estorno Mercado Livre,-33.30",
        "2026-10-28,vestuário,Magalu 02/06,150.00",
        "2026-11-01,,IOF compra internacional,4.12",
    ]
    if com_pagamento:
        linhas.insert(8, "2026-10-25,,Pagamento recebido,-1500.00")
    return ("\n".join(linhas) + "\n").encode("utf-8")


def csv_ptbr_ponto_e_virgula() -> bytes:
    """Ponto e vírgula, decimal com vírgula, linhas de cabeçalho extras, cp1252."""
    texto = (
        "Fatura do cartão;;\n"
        "Titular;FULANO DE TAL;\n"
        "Data;Estabelecimento;Valor\n"
        "05/10/2026;PADARIA SÃO JOÃO;R$ 45,90\n"
        "09/10/2026;MERCADO LIVRE PARC 03/10;R$ 99,90\n"
        "15/10/2026;SUPERMERCADO MATEUS;R$ 1.312,47\n"
        "22/10/2026;ESTORNO MERCADO LIVRE;-R$ 33,30\n"
        "Total;;R$ 1.424,97\n"
    )
    return texto.encode("cp1252")
