"""Leitor de CSV de fatura: delimitador, codificação e nomes de coluna flexíveis."""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import date

from .models import RawStatement, RawTx
from .norm import limpar_texto, norm_text, parse_date, parse_money_cents
from .ofx import adivinhar_emissor

_DATA = {"data", "date", "data compra", "data da compra", "data lancamento", "data do lancamento",
         "post date", "data transacao", "data da transacao", "dt compra"}
_DESC = {"descricao", "description", "title", "titulo", "estabelecimento", "lancamento", "historico",
         "nome", "detalhes", "descricao da compra", "local"}
_VALOR = {"valor", "amount", "valor r", "valor brl", "quantia", "value", "valor da compra", "valor em r"}
_CAT = {"categoria", "category"}
_PARC = {"parcela", "parcelas"}


def decodificar(data: bytes) -> str:
    for e in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(e)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _cabecalho(c: str) -> str:
    return norm_text(re.sub(r"[^A-Za-zÀ-ÿ0-9 ]", " ", c))


def _achar(cols: list[str], nomes: set[str]) -> int | None:
    for i, c in enumerate(cols):
        if c in nomes:
            return i
    return None


def ler_csv(data: bytes, nome_arquivo: str = "", ref: date | None = None) -> RawStatement:
    texto = decodificar(data)
    linhas = [l for l in texto.splitlines() if l.strip()]
    if len(linhas) < 2:
        raise ValueError("O CSV está vazio.")
    delim = max([";", ",", "\t"], key=lambda d: sum(l.count(d) for l in linhas[:30]))
    try:
        rows = list(csv.reader(linhas, delimiter=delim))
    except csv.Error:
        raise ValueError("Não consegui ler o CSV: há uma célula grande demais ou o arquivo está mal formado.") from None

    idx = None
    for n, row in enumerate(rows[:40]):
        cols = [_cabecalho(c) for c in row]
        d, t, v = _achar(cols, _DATA), _achar(cols, _DESC), _achar(cols, _VALOR)
        if None not in (d, t, v):
            idx = (n, d, t, v, _achar(cols, _CAT), _achar(cols, _PARC))
            break
    if idx is None:
        raise ValueError("Não encontrei as colunas de data, descrição e valor no CSV.")
    n0, ci_d, ci_t, ci_v, ci_c, ci_p = idx

    txs: list[RawTx] = []
    puladas = 0
    for row in rows[n0 + 1:]:
        if len(row) <= max(ci_d, ci_t, ci_v):
            puladas += 1
            continue
        d = parse_date(row[ci_d], ref)
        v = parse_money_cents(row[ci_v])
        desc = limpar_texto(row[ci_t])
        if d is None or v is None or v == 0 or not desc:
            puladas += 1
            continue
        if ci_p is not None and ci_p < len(row):
            if m := re.search(r"(\d{1,2})\s*(?:/|de)\s*(\d{1,2})", row[ci_p]):
                desc = f"{desc} Parcela {m[1]}/{m[2]}"
        cat = limpar_texto(row[ci_c], 60) if ci_c is not None and ci_c < len(row) and row[ci_c].strip() else None
        txs.append(RawTx(data=d, descricao=desc, bruto_cents=v, cat_arquivo=cat))
    if not txs:
        raise ValueError("Nenhuma linha válida no CSV (confira data e valor).")

    avisos = []
    if puladas:
        avisos.append(f"{puladas} linha(s) do CSV foram ignoradas (sem data, valor ou descrição).")
    datas = [t.data for t in txs]
    # Cada banco exporta colunas diferentes: a assinatura do cabeçalho separa cartões sem nome de bancos distintos.
    assinatura = "|".join(_cabecalho(c) for c in rows[n0])[:300]
    origem = "csv:" + hashlib.sha256(assinatura.encode()).hexdigest()[:16]
    return RawStatement(formato="csv", txs=txs, emissor=adivinhar_emissor(nome_arquivo),
                        total_cents=None, inicio=min(datas), fim=max(datas), avisos=avisos, origem=origem)
