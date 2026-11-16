"""Modo demonstração: a fatura de exemplo (static/exemplo) tem que continuar fictícia, conferida e servida pelo app.
A primeira impressão de quem ainda não tem o arquivo do banco depende dela."""
import re
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import importar
from tests.test_app import banco_temporario, novo_cliente  # noqa: F401 (fixture autouse: banco temporário)

ARQUIVO = Path(__file__).resolve().parent.parent / "static" / "exemplo" / "fatura-exemplo.ofx"


def test_exemplo_sai_conferido_e_mostra_o_que_o_app_faz():
    f = importar(ARQUIVO.read_bytes(), "fatura-exemplo.ofx", {}, nome="Cartão de exemplo")
    assert f.formato == "ofx" and not f.conta and f.emissor == "Cartão de exemplo"
    assert f.status == "ok" and f.total_cents == f.soma_cents  # a primeira impressão não pode ser "Divergente"
    tipos = Counter(t.tipo for t in f.txs)
    assert tipos["compra"] >= 10 and tipos["estorno"] == 1 and tipos["pagamento"] == 1 and tipos["encargo"] >= 1
    assert sum(1 for t in f.txs if t.parcela_total) >= 2          # a tela de Parcelas precisa ter o que projetar
    categorias = Counter(t.categoria for t in f.txs)
    assert len(categorias) >= 8 and categorias["Outros"] <= 3     # um gráfico de categorias que não é só "Outros"


def test_exemplo_e_ficticio():
    texto = ARQUIVO.read_bytes().decode("cp1252")
    assert "BANCO TESTE FICTICIO" in texto and "CARTAO-TESTE" in texto
    assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)  # nenhum CPF ou CNPJ
    assert "@" not in texto


def test_exemplo_e_servido_pelo_app_sem_precisar_de_login():
    r = TestClient(app).get("/exemplo/fatura-exemplo.ofx")
    assert r.status_code == 200 and r.content == ARQUIVO.read_bytes()


def test_exemplo_entra_pelo_upload_normal_e_nao_duplica():
    c = novo_cliente()
    dados = c.get("/exemplo/fatura-exemplo.ofx").content
    r = c.post("/api/faturas", files={"arquivo": ("fatura-exemplo.ofx", dados)}, data={"cartao": "Cartão de exemplo"})
    assert r.status_code == 201, r.text
    fat = r.json()
    assert fat["arquivo"] == "fatura-exemplo.ofx" and fat["emissor"] == "Cartão de exemplo" and fat["status"] == "ok"
    # clicar de novo: o app responde "já importada", e o front-end trata isso abrindo a que existe
    r2 = c.post("/api/faturas", files={"arquivo": ("fatura-exemplo.ofx", dados)}, data={"cartao": "Cartão de exemplo"})
    assert r2.status_code == 409 and r2.json()["detail"]["codigo"] == "ja_importada"
    assert len(c.get("/api/faturas").json()) == 1
    # excluir o exemplo deixa a conta vazia de novo (e dá para carregar outra vez)
    assert c.delete(f"/api/faturas/{fat['id']}").status_code == 204
    assert c.get("/api/faturas").json() == []
    assert c.post("/api/faturas", files={"arquivo": ("fatura-exemplo.ofx", dados)}, data={"cartao": "Cartão de exemplo"}).status_code == 201
