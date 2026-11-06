"""Do arquivo (OFX/CSV) à fatura conferida."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from . import config, csvparse, ofx
from .categorize import categorizar
from .models import Fatura, RawStatement, RawTx, Tx
from .norm import classify, extract_parcela, limpar_texto, norm_text


class PipelineError(Exception):
    def __init__(self, codigo: str, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.codigo, self.mensagem, self.status = codigo, mensagem, status


def detectar_formato(data: bytes, nome: str) -> str:
    n = nome.lower()
    if data[:4] == b"%PDF" or n.endswith(".pdf"):
        raise PipelineError("pdf_nao_aceito", "PDF não é aceito. Baixe a fatura em OFX ou CSV no app ou site do banco.", 415)
    if data[:2] == b"PK" or n.endswith((".xls", ".xlsx")):
        raise PipelineError("planilha_nao_aceita", "Planilha do Excel não é aceita. Exporte como CSV ou use o OFX.", 415)
    cab = data[:1500].decode("latin-1", "ignore").upper()
    if n.endswith((".ofx", ".qfx")) or "OFXHEADER" in cab or "<OFX" in cab:
        return "ofx"
    if n.endswith((".csv", ".txt", ".tsv")) or b"," in data[:2000] or b";" in data[:2000]:
        return "csv"
    raise PipelineError("formato_desconhecido", "Não reconheci o arquivo. Envie um OFX ou CSV.", 415)


_INTERNO = re.compile(r"\b(pagamento (da |de |do )?fatura|fatura (do )?cartao|aplicacao|rdb|cdb|lci|lca|tesouro)\b")


def tipo_conta(r: RawTx) -> str:
    """Extrato de conta: crédito é entrada; débito é saída (gasto), exceto pagamento de fatura e aplicações, que só
    movem o dinheiro de lugar e não podem ser contados como gasto."""
    if r.bruto_cents > 0:
        return "entrada"
    return "interno" if _INTERNO.search(norm_text(r.descricao)) else "compra"


def soma_saidas_cents(pares: list[tuple[RawTx, str]]) -> int:
    return sum(abs(r.bruto_cents) for r, tipo in pares if tipo == "compra")


def _classificar(raws: list[RawTx], sinal_compra: int) -> list[tuple[RawTx, str]]:
    return [(r, classify(r.descricao, (r.bruto_cents > 0) == (sinal_compra > 0))) for r in raws]


def soma_cents(pares: list[tuple[RawTx, str]]) -> int:
    s = 0
    for r, tipo in pares:
        a = abs(r.bruto_cents)
        if tipo in ("compra", "encargo", "saldo_anterior"):
            s += a
        elif tipo == "estorno":
            s -= a
    return s


def escolher_convencao(raws: list[RawTx], total: int | None, padrao_ofx: bool) -> tuple[int, list[str]]:
    """Define se compras são negativas (-1) ou positivas (+1). Com total, escolhe a que fecha a conta."""
    avisos: list[str] = []
    pos = sum(1 for r in raws if r.bruto_cents > 0)
    neg = sum(1 for r in raws if r.bruto_cents < 0)
    if pos == neg:
        palpite = -1 if padrao_ofx else 1
    else:
        palpite = 1 if pos > neg else -1
    if total is not None:
        for s in (palpite, -palpite):
            if abs(soma_cents(_classificar(raws, s)) - total) <= 1:
                if s != palpite:
                    avisos.append("Inverti o sinal dos valores para a conta fechar com o total da fatura.")
                return s, avisos
    avisos.append(
        f"Interpretei valores {'positivos' if palpite > 0 else 'negativos'} como compras."
        + ("" if total is not None else " Informe o total da fatura para conferir.")
    )
    return palpite, avisos


def hash_conteudo(formato: str, itens: list[tuple[str, str, int, str]]) -> str:
    """Identifica o arquivo pelo conteúdo (data, descrição, valor, fitid). Total, nome do cartão e vencimento digitados não
    entram: senão bastaria mudar um deles para importar a mesma fatura duas vezes."""
    chave_hash = json.dumps([formato, sorted(itens)], ensure_ascii=False)
    return hashlib.sha256(chave_hash.encode()).hexdigest()


def interpretar(raw: RawStatement, regras_usuario: dict[str, str], *, total_cents: int | None = None,
                vencimento: date | None = None, nome: str | None = None, arquivo: str = "") -> Fatura:
    avisos = list(raw.avisos)
    if raw.conta:
        pares = [(r, tipo_conta(r)) for r in raw.txs]
        total = None
        if total_cents is not None:
            avisos.append("O total informado foi ignorado: extrato de conta não tem total de fatura para conferir.")
        avisos.append("Extrato de conta: só as saídas contam como gasto. Entradas, pagamento de fatura e aplicações ficam fora da conta.")
    else:
        total = total_cents if total_cents is not None else raw.total_cents
        sinal, av = escolher_convencao(raw.txs, total, padrao_ofx=raw.formato == "ofx")
        pares = _classificar(raw.txs, sinal)
        avisos += av

    txs: list[Tx] = []
    for r, tipo in sorted(pares, key=lambda p: (p[0].data, p[0].descricao)):
        desc, cur, tot = extract_parcela(r.descricao) if tipo in ("compra", "estorno") else (r.descricao, None, None)
        txs.append(Tx(data=r.data, descricao=desc, valor_cents=abs(r.bruto_cents), bruto_cents=r.bruto_cents,
                      tipo=tipo, categoria=categorizar(desc, tipo, r.cat_arquivo, regras_usuario),
                      parcela_atual=cur, parcela_total=tot, fitid=r.fitid))

    if raw.conta:
        soma, status, diff = soma_saidas_cents(pares), "sem_total", None
    else:
        soma = soma_cents(pares)
        if total is None:
            status, diff = "sem_total", None
        else:
            diff = soma - total
            status = "ok" if abs(diff) <= 1 else "divergente"

    referencia = vencimento or raw.fim or max(t.data for t in txs)
    h = hash_conteudo(raw.formato, [(str(t.data), t.descricao, t.bruto_cents, t.fitid or "") for t in txs])
    return Fatura(formato=raw.formato, emissor=nome or raw.emissor, vencimento=vencimento, fechamento=raw.fim,
                  referencia=referencia, total_cents=total, soma_cents=soma, diff_cents=diff, status=status,
                  txs=txs, avisos=avisos, hash=h, arquivo=arquivo, conta=raw.conta, origem=raw.origem)


def importar(data: bytes, nome_arquivo: str, regras_usuario: dict[str, str], *, total_cents: int | None = None,
             vencimento: date | None = None, nome: str | None = None) -> Fatura:
    formato = detectar_formato(data, nome_arquivo)
    try:
        raw = ofx.ler_ofx(data, nome_arquivo) if formato == "ofx" else csvparse.ler_csv(data, nome_arquivo, vencimento)
    except ValueError as e:
        raise PipelineError("arquivo_invalido", str(e), 422)
    if len(raw.txs) > config.MAX_LINHAS:
        raise PipelineError("muitas_linhas", f"O arquivo tem {len(raw.txs)} lançamentos; o limite é {config.MAX_LINHAS}. "
                            "Exporte um período menor.", 413)
    return interpretar(raw, regras_usuario, total_cents=total_cents, vencimento=vencimento,
                       nome=limpar_texto(nome, 60) or None, arquivo=limpar_texto(nome_arquivo, 120))
