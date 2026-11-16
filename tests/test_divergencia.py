"""Divergência que explica: cada hipótese só aparece quando um valor do próprio arquivo bate com a diferença."""
from pathlib import Path

import pytest

from app.divergencia import Linha, explicar
from tests.test_app import banco_temporario, novo_cliente  # noqa: F401 (fixture autouse: banco temporário)

EXEMPLO = Path(__file__).resolve().parent.parent / "static" / "exemplo" / "fatura-exemplo.ofx"


def L(valor, tipo="compra", titulo="LOJA", data="2026-10-10"):
    return Linha(data, titulo, valor, tipo)


def codigos(linhas, total, soma=None):
    if soma is None:  # mesma conta do app: compras + encargos + saldo anterior - estornos (pagamento fica de fora)
        soma = sum(l.valor_cents if l.tipo in ("compra", "encargo", "saldo_anterior") else -l.valor_cents if l.tipo == "estorno" else 0
                   for l in linhas)
    return [e["codigo"] for e in explicar(linhas, total, soma)]


def test_sem_divergencia_nao_explica_nada():
    base = [L(10000), L(5000)]
    assert explicar(base, 15000, 15000) == []
    assert explicar(base, 15001, 15000) == []      # 1 centavo é tolerado, como na conferência
    assert explicar(base, None, 15000) == []        # sem total não há o que conferir


def test_pagamento_ja_descontado_e_o_caso_do_exemplo():
    linhas = [L(100000), L(43190), L(50000, "pagamento", "PAGAMENTO FATURA")]
    e = explicar(linhas, 143190 - 50000, 143190)
    assert e[0]["codigo"] == "pagamento_ja_descontado"
    assert "R$ 500,00" in e[0]["texto"] and "já ter descontado o pagamento" in e[0]["texto"]


def test_pagamento_unico_entre_varios():
    linhas = [L(90000), L(20000, "pagamento", "PGTO A"), L(30000, "pagamento", "PGTO B")]
    assert codigos(linhas, 60000)[0] == "pagamento_ja_descontado"   # a diferença (300) é um dos pagamentos


def test_saldo_anterior_fora_do_total():
    linhas = [L(80000), L(25000, "saldo_anterior", "SALDO FATURA ANTERIOR")]
    e = explicar(linhas, 80000, 105000)
    assert e[0]["codigo"] == "saldo_anterior" and "R$ 250,00" in e[0]["texto"]


def test_encargos_fora_do_total_juntos_ou_um_so():
    assert codigos([L(100000), L(1990, "encargo", "ANUIDADE"), L(2875, "encargo", "JUROS")], 100000)[0] == "encargos_fora_do_total"
    um = explicar([L(100000), L(1990, "encargo", "IOF"), L(2875, "encargo", "JUROS")], 100000 + 2875, 104865)
    assert um[0]["codigo"] == "encargos_fora_do_total" and "IOF" in um[0]["texto"]


def test_total_do_banco_sem_descontar_estornos():
    linhas = [L(100000), L(3500, "estorno", "ESTORNO LOJA")]
    e = explicar(linhas, 100000, 96500)          # soma menor que o total, e a diferença é o estorno
    assert e[0]["codigo"] == "estornos" and "R$ 35,00" in e[0]["texto"]


def test_linha_repetida_vira_a_primeira_pista():
    linhas = [L(8990, titulo="MERCADO X", data="2026-10-05"), L(8990, titulo="MERCADO X", data="2026-10-05"), L(20000)]
    e = explicar(linhas, 8990 + 20000, 8990 * 2 + 20000)
    assert e[0]["codigo"] == "linha_repetida" and "2 vezes" in e[0]["texto"]


def test_sinal_trocado_dobro_do_valor():
    # um estorno que na verdade era compra: o app subtrai 120, o banco soma 120 -> diferença de -240
    linhas = [L(50000), L(12000, "estorno", "LOJA Y")]
    e = explicar(linhas, 50000 + 12000, 50000 - 12000)
    assert e[0]["codigo"] == "sinal_trocado" and "talvez seja uma compra" in e[0]["texto"]
    # e o contrário: uma compra que era estorno, diferença de +2x
    c = explicar([L(50000), L(7000, titulo="LOJA Z")], 50000 - 7000, 57000)
    assert c[0]["codigo"] == "sinal_trocado" and "talvez seja um estorno" in c[0]["texto"]


def test_dia_fora_do_periodo():
    linhas = [L(30000, data="2026-10-01"), L(45000, data="2026-10-15"), L(12345, data="2026-11-07"), L(7000, data="2026-11-07")]
    e = explicar(linhas, 30000 + 45000, 30000 + 45000 + 12345 + 7000)
    assert e[0]["codigo"] == "dia_fora_do_periodo" and "07/11" in e[0]["texto"]


def test_uma_compra_com_o_valor_da_diferenca():
    linhas = [L(30000, titulo="A"), L(45678, titulo="LOJA ESTRANHA", data="2026-10-20"), L(11111, titulo="B")]
    e = explicar(linhas, 30000 + 11111, 30000 + 45678 + 11111)
    assert e[0]["codigo"] == "uma_compra" and "LOJA ESTRANHA" in e[0]["texto"]


def test_virgula_do_total_no_lugar_errado():
    linhas = [L(100000), L(43190)]
    menor = explicar(linhas, 14319, 143190)
    assert menor[0]["codigo"] == "virgula" and "10 vezes menor" in menor[0]["texto"]
    maior = explicar(linhas, 1431900, 143190)
    assert maior[0]["codigo"] == "virgula" and "10 vezes maior" in maior[0]["texto"]


def test_centavos():
    e = explicar([L(100000)], 100047, 100000)
    assert e[0]["codigo"] == "centavos" and "arredondamento" in e[0]["texto"]


def test_sem_pista_exata_diz_para_que_lado_erra():
    assert codigos([L(100000)], 100777)[0] == "faltando"
    assert codigos([L(100000)], 99123)[0] == "sobrando"


def test_no_maximo_tres_causas_sem_repetir_codigo():
    linhas = [L(100000), L(50000, "pagamento", "PGTO"), L(50000, titulo="X"), L(1990, "encargo", "IOF")]
    e = explicar(linhas, 100000 + 1990, 151990)
    assert len(e) <= 3 and len({x["codigo"] for x in e}) == len(e)


@pytest.mark.parametrize("centavos,esperado", [(5, "R$ 0,05"), (100, "R$ 1,00"), (143190, "R$ 1.431,90"),
                                               (123456789, "R$ 1.234.567,89"), (-50000, "R$ 500,00")])
def test_formata_reais_com_virgula_e_ponto_de_milhar(centavos, esperado):
    from app.divergencia import _brl
    assert _brl(centavos) == esperado


# ---------- pela API ----------

def _exemplo_divergente():
    """O arquivo de exemplo com o saldo do OFX que já desconta o pagamento de R$ 500 (o formato que gerava 'Divergente')."""
    return EXEMPLO.read_bytes().replace(b"<BALAMT>-1431.90</BALAMT>", b"<BALAMT>-931.90</BALAMT>")


def test_api_explica_a_divergencia_do_exemplo():
    c = novo_cliente()
    r = c.post("/api/faturas", files={"arquivo": ("f.ofx", _exemplo_divergente())})
    assert r.status_code == 201, r.text
    rec = r.json()["reconciliacao"]
    assert rec["status"] == "divergente" and rec["diff_cents"] == 50000
    assert rec["explicacoes"][0]["codigo"] == "pagamento_ja_descontado"
    assert len(rec["explicacoes"]) <= 3


def test_api_nao_explica_quando_esta_conferido_e_some_ao_corrigir_o_total():
    c = novo_cliente()
    ok = c.post("/api/faturas", files={"arquivo": ("f.ofx", EXEMPLO.read_bytes())}).json()
    assert ok["reconciliacao"]["status"] == "ok" and ok["reconciliacao"]["explicacoes"] == []
    c.delete(f"/api/faturas/{ok['id']}")
    div = c.post("/api/faturas", files={"arquivo": ("f.ofx", _exemplo_divergente())}).json()
    assert div["reconciliacao"]["explicacoes"]
    # digitar o total que a soma pede resolve: conferido e sem explicações
    corrigido = c.patch(f"/api/faturas/{div['id']}", json={"total": "1431,90"}).json()
    assert corrigido["reconciliacao"]["status"] == "ok" and corrigido["reconciliacao"]["explicacoes"] == []


def test_api_extrato_de_conta_nao_tem_explicacao():
    c = novo_cliente()
    nubank = Path(__file__).resolve().parent / "bancos" / "nubank-conta.ofx"
    f = c.post("/api/faturas", files={"arquivo": ("c.ofx", nubank.read_bytes())}).json()
    assert f["reconciliacao"]["status"] == "sem_total" and f["reconciliacao"]["explicacoes"] == []
