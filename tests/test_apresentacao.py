"""Descrição limpa, privacidade de terceiros, categorização nova e cabeçalhos de produção."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.categorize import CATEGORIAS_EDITAVEIS, categorizar
from app.descricao import apresentar, sanitizar
from app.main import app
from tests.test_app import banco_temporario, novo_cliente  # noqa: F401 (fixture autouse: banco temporário)

PIX_PESSOA = ("Transferência enviada pelo Pix - DHANIEL LYVIO DO NASCIMENTO MORAIS - •••.651.653-•• - "
              "BCO DO BRASIL S.A. (0001) Agência: 1638 Conta: 30652-5")
PIX_LOJA = ("Transferência enviada pelo Pix - GRILL HAUS - 48.568.213/0002-21 - BCO BRADESCO S.A. (0237) "
            "Agência: 2293 Conta: 25747-8")
PIX_MERCADO_PAGO = ("Transferência enviada pelo Pix - LOJA X - 11.111.111/0001-11 - MERCADO PAGO IP (0323) "
                    "Agência: 1 Conta: 1-1")

# Extrato de conta no formato CSV do Nubank (Data, Valor, Identificador, Descrição)
CSV_CONTA = "\n".join([
    "Data,Valor,Identificador,Descrição",
    f"31/10/2026,-45.00,id1,{PIX_PESSOA}",
    f"18/10/2026,-80.00,id2,{PIX_LOJA}",
    "28/10/2026,-33.00,id3,Compra no débito - FACEBURGUER DELIVERY",
    "20/10/2026,2000.00,id4,Transferência Recebida - Fernanda Alves de Oliveira - •••.142.883-•• - "
    "NU PAGAMENTOS - IP (0260) Agência: 1 Conta: 33697065-4",
]).encode()


def test_titulo_e_detalhe_de_pix_para_pessoa():
    a = apresentar(PIX_PESSOA)
    assert a.titulo == "Dhaniel Lyvio do Nascimento Morais"
    assert a.detalhe == "Pix enviado · Banco do Brasil"
    assert a.transferencia and a.pessoa


def test_titulo_de_compra_no_debito_e_nupay():
    assert apresentar("Compra no débito - FACEBURGUER DELIVERY").titulo == "Faceburguer Delivery"
    a = apresentar("Compra no débito via NuPay - iFood")
    assert (a.titulo, a.detalhe) == ("iFood", "Débito via NuPay")


def test_descricao_de_cartao_fica_como_veio():
    a = apresentar("UBER *TRIP HELP.UBER.COM")
    assert a.titulo == "UBER *TRIP HELP.UBER.COM" and a.detalhe is None


@pytest.mark.parametrize("texto", [PIX_PESSOA, PIX_LOJA, "Pix enviado 12345678901 JOAO", "TED 12.345.678/0001-90 EMPRESA"])
def test_sanitizar_tira_documentos_agencia_e_conta(texto):
    s = sanitizar(texto)
    for proibido in ("651.653", "48.568.213", "0002-21", "12345678901", "12.345.678", "Agência", "Conta:", "1638", "30652"):
        assert proibido not in s


def test_categorias_novas():
    assert "Transferências" in CATEGORIAS_EDITAVEIS
    assert categorizar(PIX_PESSOA, "compra", None, {}) == "Transferências"
    assert categorizar(PIX_LOJA, "compra", None, {}) == "Alimentação"            # "grill" no nome
    assert categorizar("Compra no débito - FACEBURGUER DELIVERY", "compra", None, {}) == "Alimentação"
    # o banco do recebedor não decide a categoria
    assert categorizar(PIX_MERCADO_PAGO, "compra", None, {}) == "Outros"


@pytest.mark.parametrize("texto", ["SAQUE EXTRA", "PIX 99 REAIS", "SEGURO FIANCA ALUGUEL XYZ"])
def test_falsos_positivos_antigos_nao_voltam(texto):
    assert categorizar(texto, "compra", None, {}) == "Outros"


def test_regra_do_usuario_continua_vencendo():
    from app.categorize import chave
    assert categorizar(PIX_PESSOA, "compra", None, {chave(PIX_PESSOA): "Lazer"}) == "Lazer"


def test_api_nunca_devolve_documento_agencia_ou_conta():
    c = novo_cliente()
    r = c.post("/api/faturas", files={"arquivo": ("extrato.csv", CSV_CONTA)})
    assert r.status_code == 201, r.text
    corpo = r.text
    for proibido in ("651.653", "48.568.213", "142.883", "Agência", "Conta: ", "30652", "33697065"):
        assert proibido not in corpo
    fat = r.json()
    por_titulo = {t["titulo"]: t for t in fat["transacoes"]}
    assert por_titulo["Dhaniel Lyvio do Nascimento Morais"]["categoria"] == "Transferências"
    assert por_titulo["Dhaniel Lyvio do Nascimento Morais"]["detalhe"] == "Pix enviado · Banco do Brasil"
    assert por_titulo["Grill Haus"]["categoria"] == "Alimentação"
    # o resumo também sai limpo
    resumo = c.get(f"/api/resumo?fatura_id={fat['id']}").text
    assert "651.653" not in resumo and "Agência" not in resumo


def test_migracao_recategoriza_so_o_que_estava_em_outros(tmp_path, monkeypatch):  # noqa
    c = novo_cliente()
    fat = c.post("/api/faturas", files={"arquivo": ("extrato.csv", CSV_CONTA)}).json()
    ids = {t["titulo"]: t["id"] for t in fat["transacoes"]}
    # simula um banco antigo: tudo em "Outros" e a versão do schema anterior
    with sqlite3.connect(config.DB_PATH) as s:
        s.execute("UPDATE transacoes SET categoria='Outros' WHERE tipo='compra'")
        s.execute("UPDATE transacoes SET categoria='Lazer' WHERE id=?", (ids["Grill Haus"],))  # escolha da pessoa
        # Um banco dessa época guarda a descrição crua (hoje a importação já grava limpa); a migração 4 precisa do CPF
        # para reconhecer o Pix para pessoa física, e roda antes da 6, que limpa.
        s.execute("UPDATE transacoes SET descricao=? WHERE id=?", (PIX_PESSOA, ids["Dhaniel Lyvio do Nascimento Morais"]))
        s.execute("UPDATE transacoes SET descricao=? WHERE id=?", (PIX_LOJA, ids["Grill Haus"]))
        s.execute("PRAGMA user_version=3")
    db._prontos.clear()
    novo = {t["titulo"]: t["categoria"] for t in c.get(f"/api/faturas/{fat['id']}").json()["transacoes"]}
    assert novo["Dhaniel Lyvio do Nascimento Morais"] == "Transferências"
    assert novo["Faceburguer Delivery"] == "Alimentação"
    assert novo["Grill Haus"] == "Lazer"  # o que não estava em Outros fica como está


def test_hsts_so_em_https_e_cookie_seguro_forcado(monkeypatch):
    http = TestClient(app)
    assert "strict-transport-security" not in http.get("/api/health").headers
    https = TestClient(app, base_url="https://testserver")
    h = https.get("/api/health").headers
    assert h["strict-transport-security"].startswith("max-age=")
    monkeypatch.setattr(config, "COOKIE_SEGURO", True)
    r = http.post("/api/auth/cadastro", json={"nome": "Bia", "email": "bia@exemplo.com", "senha": "uma frase longa e boa"})
    assert r.status_code == 201 and "secure" in r.headers["set-cookie"].lower()


def test_casco_do_app_revalida_e_api_nao_guarda():
    c = TestClient(app)
    assert c.get("/css/app.css").headers["cache-control"] == "no-cache"
    assert c.get("/").headers["cache-control"] == "no-cache"
    assert c.get("/api/health").headers["cache-control"] == "no-store"
