"""Fase 0: limitador que não perde o contador de quem está bloqueado, desfazer que só aceita o que é editável,
e descrição de terceiros (CPF/CNPJ/agência/conta) limpa também no banco."""
import sqlite3

import pytest

from app import config, db, seguranca
from app.descricao import apresentar, sanitizar
from tests import samples
from tests.test_apresentacao import CSV_CONTA, PIX_LOJA, PIX_MERCADO_PAGO, PIX_PESSOA
from tests.test_app import banco_temporario, novo_cliente  # noqa: F401 (fixture autouse: banco temporário)

PROIBIDO = ("651.653", "48.568.213", "142.883", "Agência", "Conta: ", "30652", "33697065", "25747")


# ---------- limitador ----------

def test_limitador_bloqueia_e_nao_cria_entradas_ao_consultar():
    lim = seguranca.Limite(3, 60, max_chaves=10)
    for _ in range(3):
        lim.registrar("alvo")
    assert lim.espera("alvo") > 0
    for i in range(50):  # consultar chaves desconhecidas não pode encher a tabela
        assert lim.espera(f"curioso-{i}") == 0
    assert len(lim._eventos) == 1


def test_encher_a_tabela_nao_apaga_o_contador_de_quem_esta_bloqueado():
    lim = seguranca.Limite(3, 60, max_chaves=10)
    for _ in range(3):
        lim.registrar("alvo")
    assert lim.espera("alvo") > 0
    for i in range(500):  # quem manda muitas chaves diferentes para estourar o teto
        lim.registrar(f"ip-{i}")
    assert len(lim._eventos) <= 10
    assert lim.espera("alvo") > 0  # o bloqueio sobrevive; antes do conserto tudo era zerado


def test_limitador_expira_pela_janela(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(seguranca.time, "monotonic", lambda: t[0])
    lim = seguranca.Limite(2, 10)
    lim.registrar("a")
    lim.registrar("a")
    assert lim.espera("a") > 0
    t[0] += 11
    assert lim.espera("a") == 0 and "a" not in lim._eventos


def test_limitador_so_expulsa_bloqueados_se_nao_houver_outro():
    lim = seguranca.Limite(1, 60, max_chaves=5)
    for i in range(5):
        lim.registrar(f"b{i}")  # todos já no limite (maximo=1)
    lim.registrar("novo")
    assert len(lim._eventos) <= 5 and "novo" in lim._eventos


# ---------- desfazer ----------

def _importar_ofx(c):
    r = c.post("/api/faturas", files={"arquivo": ("fat.ofx", samples.ofx_cartao())})
    assert r.status_code == 201, r.text
    return r.json()


def test_desfazer_recusa_categoria_fixa():
    c = novo_cliente()
    fat = _importar_ofx(c)
    tx = next(t for t in fat["transacoes"] if t["tipo"] == "compra")
    for fixa in ("Pagamento de fatura", "Entradas", "Juros e taxas", "Investimentos"):
        r = c.post("/api/transacoes/restaurar",
                   json={"itens": [{"id": tx["id"], "categoria": fixa}], "chave": "x", "categoria_regra": "Outros"})
        assert r.status_code == 422 and r.json()["detail"]["codigo"] == "categoria_invalida", fixa
        r = c.post("/api/transacoes/restaurar", json={"itens": [], "chave": "x", "categoria_regra": fixa})
        assert r.status_code == 422, fixa
    atual = {t["id"]: t["categoria"] for t in c.get(f"/api/faturas/{fat['id']}").json()["transacoes"]}
    assert atual[tx["id"]] == tx["categoria"]


def test_desfazer_nao_recategoriza_pagamento_nem_entrada():
    c = novo_cliente()
    fat = _importar_ofx(c)
    pag = next(t for t in fat["transacoes"] if t["tipo"] == "pagamento")
    compra = next(t for t in fat["transacoes"] if t["tipo"] == "compra")
    ch = c.patch(f"/api/transacoes/{compra['id']}", json={"categoria": "Casa"}).json()
    # a chamada é válida (a chave existe e a categoria é editável), mas traz o id de um pagamento: ele não pode mudar
    r = c.post("/api/transacoes/restaurar",
               json={"itens": [{"id": pag["id"], "categoria": "Lazer"}], "chave": ch["chave"], "categoria_regra": "Outros"})
    assert r.status_code == 204
    atual = {t["id"]: t["categoria"] for t in c.get(f"/api/faturas/{fat['id']}").json()["transacoes"]}
    assert atual[pag["id"]] == pag["categoria"] == "Pagamento de fatura"


def test_desfazer_normal_continua_funcionando():
    c = novo_cliente()
    fat = _importar_ofx(c)
    compra = next(t for t in fat["transacoes"] if t["tipo"] == "compra")
    ch = c.patch(f"/api/transacoes/{compra['id']}", json={"categoria": "Casa"}).json()
    r = c.post("/api/transacoes/restaurar",
               json={"itens": ch["anteriores"], "chave": ch["chave"], "categoria_regra": ch["categoria_anterior"]})
    assert r.status_code == 204
    atual = {t["id"]: t["categoria"] for t in c.get(f"/api/faturas/{fat['id']}").json()["transacoes"]}
    assert atual[compra["id"]] == compra["categoria"]


# ---------- descrição de terceiros no banco ----------

def _descricoes_no_banco():
    with sqlite3.connect(config.DB_PATH) as s:
        return [r[0] for r in s.execute("SELECT descricao FROM transacoes")]


def test_banco_nao_guarda_documento_agencia_nem_conta():
    c = novo_cliente()
    assert c.post("/api/faturas", files={"arquivo": ("extrato.csv", CSV_CONTA)}).status_code == 201
    tudo = "\n".join(_descricoes_no_banco())
    for p in PROIBIDO:
        assert p not in tudo, p
    assert any("Pix" in d or "Transfer" in d for d in _descricoes_no_banco())  # o resto da descrição fica


def test_categoria_e_regra_continuam_vindo_da_descricao_crua():
    c = novo_cliente()
    fat = c.post("/api/faturas", files={"arquivo": ("extrato.csv", CSV_CONTA)}).json()
    por_titulo = {t["titulo"]: t for t in fat["transacoes"]}
    # "Transferências" depende de o CPF existir na descrição crua; limpar antes de categorizar quebraria isto
    assert por_titulo["Dhaniel Lyvio do Nascimento Morais"]["categoria"] == "Transferências"
    assert por_titulo["Grill Haus"]["categoria"] == "Alimentação"


def test_titulo_e_detalhe_iguais_com_a_descricao_crua_ou_limpa():
    for cru in (PIX_PESSOA, PIX_LOJA, PIX_MERCADO_PAGO):
        a, b = apresentar(cru), apresentar(sanitizar(cru))
        assert (a.titulo, a.detalhe) == (b.titulo, b.detalhe), cru


@pytest.mark.parametrize("texto", [PIX_PESSOA, PIX_LOJA, PIX_MERCADO_PAGO, "Pix enviado 12345678901 JOAO",
                                   "Compra no débito - LOJA", ""])
def test_sanitizar_e_idempotente(texto):
    assert sanitizar(sanitizar(texto)) == sanitizar(texto)


def test_reimportar_arquivo_mais_completo_ainda_casa_com_descricao_limpa():
    """O arquivo novo chega cru e o banco tem a descrição limpa: a comparação limpa os dois lados, senão duplicaria."""
    c = novo_cliente()
    primeiro = c.post("/api/faturas", files={"arquivo": ("extrato.csv", CSV_CONTA)})
    assert primeiro.status_code == 201
    n0 = len(primeiro.json()["transacoes"])
    mais = CSV_CONTA + "\n02/11/2026,-10.00,id9,Compra no débito - PADARIA NOVA".encode()
    r = c.post("/api/faturas", files={"arquivo": ("extrato2.csv", mais)})
    assert r.status_code == 200, r.text
    assert r.json()["atualizada"]["novos"] == 1 and len(r.json()["transacoes"]) == n0 + 1
    assert len(c.get("/api/faturas").json()) == 1


def test_migracao_6_limpa_o_que_ja_estava_guardado_e_faz_copia(tmp_path):
    c = novo_cliente()
    fat = c.post("/api/faturas", files={"arquivo": ("extrato.csv", CSV_CONTA)}).json()
    alvo = next(t for t in fat["transacoes"] if t["titulo"] == "Dhaniel Lyvio do Nascimento Morais")
    # simula um banco antigo: descrição crua e a versão do schema anterior
    with sqlite3.connect(config.DB_PATH) as s:
        s.execute("UPDATE transacoes SET descricao=? WHERE id=?", (PIX_PESSOA, alvo["id"]))
        s.execute("PRAGMA user_version=5")
    assert "651.653" in "\n".join(_descricoes_no_banco())
    db._prontos.clear()
    c.get(f"/api/faturas/{fat['id']}")  # a primeira requisição migra
    assert "651.653" not in "\n".join(_descricoes_no_banco())
    copia = tmp_path / "mare-backup-antes-v6.db"
    assert copia.exists()
    with sqlite3.connect(copia) as s:  # a cópia guarda o dado original, para o caso de algo dar errado
        assert s.execute("SELECT COUNT(*) FROM transacoes WHERE descricao LIKE '%651.653%'").fetchone()[0] == 1
    novo = {t["titulo"]: t["categoria"] for t in c.get(f"/api/faturas/{fat['id']}").json()["transacoes"]}
    assert novo["Dhaniel Lyvio do Nascimento Morais"] == "Transferências"  # a categoria aprendida não mudou
