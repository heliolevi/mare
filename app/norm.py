"""Funções de normalização: dinheiro, datas, texto, parcelas."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


_INVISIVEIS = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")


def limpar_texto(s: str | None, limite: int = 200) -> str:
    """Texto vindo de arquivo de terceiros: sem caracteres de controle nem de direção (que disfarçam texto), espaços
    normalizados e tamanho limitado."""
    t = _INVISIVEIS.sub(" ", s or "")
    return re.sub(r"\s+", " ", t).strip()[:limite]


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(s).lower()).strip()


MAX_CENTS = 10**12  # R$ 10 bilhões: acima disso o valor é tratado como inválido (evita estouro no SQLite e números absurdos)


def parse_money_cents(value) -> int | None:
    """'1.234,56', '-1234.56', '(12,00)', 'R$ 9,90', '12,00-' -> centavos (com sinal). Inválido ou gigante -> None."""
    if value is None:
        return None
    t = str(value).strip().replace(" ", " ")
    if not t or len(t) > 40:
        return None
    t = re.sub(r"(?i)r\$|brl|\s", "", t)
    neg = (t.startswith("(") and t.endswith(")")) or t.startswith("-") or t.endswith("-")
    t = t.strip("()").strip("+-")
    if not t or re.search(r"[^\d.,]", t):
        return None
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".") if t.count(",") == 1 else t.replace(",", "")
    elif "." in t and re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")  # 1.234 = mil duzentos e trinta e quatro
    try:
        cents = int((Decimal(t) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None
    if cents > MAX_CENTS:
        return None
    return -cents if neg else cents


def parse_date(value: str, ref: date | None = None) -> date | None:
    """Aceita 20261015..., 2026-10-15, 15/10/2026, 15/10/26, 15-10-2026 e 15/10 (ano inferido de ref)."""
    if not value:
        return None
    s = str(value).strip()
    ref = ref or date.today()
    d = _parse_date(s, ref)
    return d if d and ANO_MIN <= d.year <= ANO_MAX else None


ANO_MIN, ANO_MAX = 2000, 2100


def _parse_date(s: str, ref: date) -> date | None:
    try:
        if m := re.match(r"^(\d{4})(\d{2})(\d{2})(?:\d{0,6})?(?:\[.*\])?$", s):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})", s):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.match(r"^(\d{2})[/.\-](\d{2})[/.\-](\d{4})", s):
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.match(r"^(\d{2})[/.\-](\d{2})[/.\-](\d{2})$", s):
            return date(2000 + int(m[3]), int(m[2]), int(m[1]))
        if m := re.match(r"^(\d{2})[/.\-](\d{2})$", s):
            d = date(ref.year, int(m[2]), int(m[1]))
            return d.replace(year=d.year - 1) if d > ref + timedelta(days=7) else d
    except ValueError:
        return None
    return None


_PARCELA_A = re.compile(r"(?i)\bparc(?:ela)?\.?\s*(\d{1,2})\s*(?:/|de)\s*(\d{1,2})\b")
_PARCELA_B = re.compile(r"(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})\s*$")


def extract_parcela(desc: str) -> tuple[str, int | None, int | None]:
    """Devolve (descrição limpa, parcela atual, total). 'LOJA Parcela 3/10' -> ('LOJA', 3, 10)."""
    for rx in (_PARCELA_A, _PARCELA_B):
        m = rx.search(desc)
        if not m:
            continue
        cur, tot = int(m[1]), int(m[2])
        if 2 <= tot <= 60 and 1 <= cur <= tot:
            clean = (desc[: m.start()] + " " + desc[m.end():]).strip(" -*/")
            return re.sub(r"\s+", " ", clean) or desc, cur, tot
    return desc, None, None


_ENCARGO = re.compile(r"\b(juros|multa|iof|encargos?|anuidade|mora|rotativo|tarifa|seguro fatura)\b")
_SALDO = re.compile(r"\b(saldo (restante|anterior|devedor)|fatura anterior)\b")
_PAGAMENTO = re.compile(r"\b(pagamento|pgto|pagto|pag fatura|obrigado)\b")


def classify(desc: str, same_sign_as_purchase: bool) -> str:
    """compra | encargo | saldo_anterior | estorno | pagamento"""
    t = norm_text(desc)
    if same_sign_as_purchase:
        if _SALDO.search(t) and "pagamento" not in t:
            return "saldo_anterior"
        if _ENCARGO.search(t):
            return "encargo"
        return "compra"
    return "pagamento" if _PAGAMENTO.search(t) else "estorno"
