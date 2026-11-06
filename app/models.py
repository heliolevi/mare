from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RawTx:
    """Transação como veio do arquivo. bruto_cents mantém o sinal original."""
    data: date
    descricao: str
    bruto_cents: int
    fitid: str | None = None
    cat_arquivo: str | None = None


@dataclass
class RawStatement:
    formato: str                      # "ofx" | "csv"
    txs: list[RawTx]
    emissor: str | None = None
    total_cents: int | None = None    # total da fatura, se o arquivo informar (sempre positivo)
    inicio: date | None = None
    fim: date | None = None
    avisos: list[str] = field(default_factory=list)
    conta: bool = False               # extrato de conta corrente (não de cartão): sem conferência de total
    origem: str | None = None         # impressão digital de quem gerou o arquivo (cartão/conta); nunca sai da API


@dataclass
class Tx:
    data: date
    descricao: str
    valor_cents: int                  # sempre positivo; o sinal vem do tipo
    bruto_cents: int
    tipo: str                         # compra | encargo | saldo_anterior | estorno | pagamento | entrada | interno
    categoria: str
    parcela_atual: int | None = None
    parcela_total: int | None = None
    fitid: str | None = None


@dataclass
class Fatura:
    formato: str
    emissor: str | None
    vencimento: date | None
    fechamento: date | None
    referencia: date
    total_cents: int | None
    soma_cents: int
    diff_cents: int | None
    status: str                       # ok | divergente | sem_total
    txs: list[Tx]
    avisos: list[str]
    hash: str
    arquivo: str
    conta: bool = False
    origem: str | None = None
