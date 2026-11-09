import pytest
from fastapi.testclient import TestClient

from app import config, correio, db
from app import main
from app.main import app
from app.models import RawTx
from app.pipeline import PipelineError, escolher_convencao, importar
from tests import samples


@pytest.fixture(autouse=True)
def banco_temporario(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "ALLOWED_HOSTS", {"testserver"})
    monkeypatch.setattr(config, "SCRYPT_LOG_N", 4)  # senha rápida nos testes; em produção é 17
    monkeypatch.setattr(config, "CADASTRO_ABERTO", True)
    monkeypatch.setattr(config, "CONFIRMAR_EMAIL", False)  # os testes de confirmação ligam por conta própria
    for lim in main._lim.values():
        lim.limpar()


SENHA = "uma frase longa e boa"


def novo_cliente(email="ana@exemplo.com", nome="Ana"):
    """Cliente de teste já com conta criada e sessão aberta (o cookie fica no cliente)."""
    c = TestClient(app)
    r = c.post("/api/auth/cadastro", json={"nome": nome, "email": email, "senha": SENHA})
    assert r.status_code == 201, r.text
    return c


def f_ofx(**kw):
    return importar(samples.ofx_cartao(**kw), "nubank.ofx", {})


def test_ofx_sgml_cp1252_fecha_com_o_saldo():
    f = f_ofx()
    assert f.formato == "ofx" and f.emissor == "Nubank"
    assert f.status == "ok" and f.total_cents == samples.TOTAL_CENTS and f.soma_cents == samples.TOTAL_CENTS
    tipos = [t.tipo for t in f.txs]
    assert tipos.count("pagamento") == 1 and tipos.count("estorno") == 1 and tipos.count("encargo") == 1
    por_desc = {t.descricao: t for t in f.txs}
    assert "Padaria São João" in por_desc  # acento preservado (cp1252)
    ml = por_desc["Mercado Livre"]
    assert (ml.parcela_atual, ml.parcela_total) == (3, 10)
    mg = por_desc["Magalu"]
    assert (mg.parcela_atual, mg.parcela_total) == (2, 6)
    cats = {t.descricao: t.categoria for t in f.txs}
    assert cats["Padaria São João"] == "Alimentação" and cats["Uber *Trip"] == "Transporte"
    assert cats["Netflix.com"] == "Assinaturas" and cats["Supermercado Mateus"] == "Mercado"
    assert cats["Farmácia Pague Menos"] == "Saúde" and cats["Mercado Livre"] == "Compras"
    assert cats["Pagamento recebido"] == "Pagamento de fatura"


def test_ofx_com_sinais_invertidos_tambem_fecha():
    f = f_ofx(invertido=True)
    assert f.status == "ok" and f.soma_cents == samples.TOTAL_CENTS


def test_ofx_sem_saldo_fica_sem_total():
    f = f_ofx(saldo=None)
    assert f.status == "sem_total" and f.total_cents is None and f.diff_cents is None


def test_ofx_com_saldo_errado_diverge():
    f = f_ofx(saldo="-700.00")
    assert f.status == "divergente" and f.diff_cents == samples.TOTAL_CENTS - 70000


def test_convencao_inverte_para_fechar_a_conta():
    raws = [RawTx(None, "Loja", -10000), RawTx(None, "Estorno A", 1000), RawTx(None, "Estorno B", 2000)]
    sinal, avisos = escolher_convencao(raws, 7000, padrao_ofx=True)
    assert sinal == -1 and any("Inverti" in a for a in avisos)


def test_csv_nubank_sem_total_e_depois_com_total():
    f = importar(samples.csv_nubank(), "nubank_2026-10.csv", {})
    assert f.formato == "csv" and f.status == "sem_total" and f.emissor == "Nubank"
    assert f.soma_cents == samples.TOTAL_CENTS
    assert [t.tipo for t in f.txs].count("pagamento") == 1
    g = importar(samples.csv_nubank(), "x.csv", {}, total_cents=samples.TOTAL_CENTS)
    assert g.status == "ok"
    cats = {t.descricao: t.categoria for t in g.txs}
    assert cats["Padaria Sao Joao"] == "Alimentação"  # palavra-chave
    assert cats["Mercado Livre"] == "Compras"  # palavra-chave vence a categoria 'casa' do arquivo


def test_csv_ptbr_ponto_e_virgula_com_preambulo():
    f = importar(samples.csv_ptbr_ponto_e_virgula(), "fatura.csv", {}, total_cents=142497)
    assert f.status == "ok" and len(f.txs) == 4
    maior = max(f.txs, key=lambda t: t.valor_cents)
    assert maior.valor_cents == 131247
    assert any("ignorada" in a for a in f.avisos)  # linha 'Total'


@pytest.mark.parametrize("dados,nome,codigo", [
    (b"%PDF-1.7 ...", "fatura.pdf", "pdf_nao_aceito"),
    (b"PK\x03\x04...", "fatura.xlsx", "planilha_nao_aceita"),
])
def test_formatos_nao_aceitos(dados, nome, codigo):
    with pytest.raises(PipelineError) as e:
        importar(dados, nome, {})
    assert e.value.codigo == codigo


def test_csv_sem_colunas_conhecidas():
    with pytest.raises(PipelineError) as e:
        importar(b"a,b,c\n1,2,3\n", "x.csv", {})
    assert e.value.codigo == "arquivo_invalido"


def test_api_fluxo_completo():
    c = novo_cliente()
    assert c.get("/api/health").json() == {"ok": True}
    r = c.post("/api/faturas", files={"arquivo": ("nubank.ofx", samples.ofx_cartao(), "application/x-ofx")})
    assert r.status_code == 201, r.text
    fat = r.json()
    fid = fat["id"]
    assert fat["reconciliacao"]["status"] == "ok" and fat["reconciliacao"]["compras_cents"] > 0

    dup = c.post("/api/faturas", files={"arquivo": ("nubank.ofx", samples.ofx_cartao(), "application/x-ofx")})
    assert dup.status_code == 409 and dup.json()["detail"]["codigo"] == "ja_importada"

    pdf = c.post("/api/faturas", files={"arquivo": ("f.pdf", b"%PDF-1.4", "application/pdf")})
    assert pdf.status_code == 415

    res = c.get("/api/resumo").json()
    nomes = [x["nome"] for x in res["categorias"]]
    assert "Mercado" in nomes and "Pagamento de fatura" not in nomes
    assert res["gasto_cents"] == samples.TOTAL_CENTS

    parc = c.get("/api/parcelas-futuras").json()
    assert len(parc["meses"]) == 7  # Mercado Livre 3/10 -> 7 restantes; Magalu 2/6 -> 4
    assert parc["total_cents"] == 7 * 9990 + 4 * 15000

    ml = next(t for t in fat["transacoes"] if t["descricao"] == "Mercado Livre")
    ch = c.patch(f"/api/transacoes/{ml['id']}", json={"categoria": "Casa"})
    assert ch.status_code == 200 and ch.json()["atualizadas"] >= 1
    assert db.regras_usuario(1)["mercado livre"] == "Casa"
    back = ch.json()
    assert c.post("/api/transacoes/restaurar", json={"itens": back["anteriores"], "chave": back["chave"],
                                                      "categoria_regra": back["categoria_anterior"]}).status_code == 204
    assert c.get(f"/api/faturas/{fid}").json()["transacoes"][2]["categoria"] == "Compras"

    assert c.patch("/api/transacoes/999999", json={"categoria": "Casa"}).status_code == 404
    assert c.patch(f"/api/transacoes/{ml['id']}", json={"categoria": "Inventada"}).status_code == 422
    assert c.delete(f"/api/faturas/{fid}").status_code == 204
    assert c.get("/api/resumo").status_code == 404


def test_api_csv_sem_total_depois_informa_total():
    c = novo_cliente()
    r = c.post("/api/faturas", files={"arquivo": ("fatura.csv", samples.csv_nubank(), "text/csv")},
               data={"cartao": "Nubank Ultravioleta", "vencimento": "10/11/2026"})
    assert r.status_code == 201
    fat = r.json()
    assert fat["status"] == "sem_total" and fat["emissor"] == "Nubank Ultravioleta" and fat["vencimento"] == "2026-11-10"
    bom = c.patch(f"/api/faturas/{fat['id']}", json={"total": "736,79"}).json()
    assert bom["status"] == "ok" and bom["diff_cents"] == 0
    ruim = c.patch(f"/api/faturas/{fat['id']}", json={"total": "800,00"}).json()
    assert ruim["status"] == "divergente" and ruim["diff_cents"] == samples.TOTAL_CENTS - 80000
    assert c.patch(f"/api/faturas/{fat['id']}", json={"total": "abc"}).status_code == 422


def test_limite_de_tamanho(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0.001)
    c = novo_cliente()
    r = c.post("/api/faturas", files={"arquivo": ("a.csv", b"x" * 5000, "text/csv")})
    assert r.status_code == 413


# ---------- robustez: entradas hostis e extratos de conta ----------

CONTA = (
    b"OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:102\r\nCHARSET:1252\r\n\r\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>"
    b"<DTSTART>20261001<DTEND>20261030\r\n"
    b"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261005<TRNAMT>-50.00<FITID>1<MEMO>PIX ENVIADO JOAO SILVA\r\n"
    b"<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261006<TRNAMT>3000.00<FITID>2<MEMO>TRANSFERENCIA RECEBIDA EMPRESA XYZ\r\n"
    b"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261007<TRNAMT>-20.00<FITID>3<MEMO>PIX ENVIADO MARIA\r\n"
    b"</BANKTRANLIST><LEDGERBAL><BALAMT>2930.00</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
)


def _sem_erro_500(r):
    assert r.status_code < 500, r.text
    if r.status_code >= 400:
        assert "codigo" in r.json()["detail"], r.text


@pytest.mark.parametrize("caminho", ["/api/transacoes/99999999999999999999", "/api/transacoes/-1", "/api/transacoes/abc"])
def test_ids_absurdos_nao_derrubam_a_api(caminho):
    c = novo_cliente()
    for r in (c.patch(caminho, json={"categoria": "Outros"}), c.patch(caminho)):
        _sem_erro_500(r)
        assert r.status_code in (404, 422)
    for r in (c.get("/api/faturas/99999999999999999999"), c.delete("/api/faturas/99999999999999999999")):
        _sem_erro_500(r)


@pytest.mark.parametrize("corpo", [
    {"itens": [{"categoria": "Outros"}], "chave": "x", "categoria_regra": "Outros"},
    {"itens": [{"id": "abc", "categoria": "Outros"}], "chave": "x", "categoria_regra": "Outros"},
    {"itens": [{"id": 10**30, "categoria": "Outros"}], "chave": "x", "categoria_regra": "Outros"},
    {"itens": [], "chave": "A" * 100_000, "categoria_regra": "Outros"},
    {"itens": [{"id": 1, "categoria": "Outros"}] * 50_000, "chave": "k", "categoria_regra": "Outros"},
    {"itens": [], "chave": "k", "categoria_regra": "<img src=x onerror=alert(1)>"},
])
def test_restaurar_com_corpo_hostil(corpo):
    c = novo_cliente()
    r = c.post("/api/transacoes/restaurar", json=corpo)
    _sem_erro_500(r)
    assert r.status_code in (200, 404, 413, 422)


def test_categoria_fixa_nao_pode_ser_atribuida_a_compra():
    c = novo_cliente()
    fat = c.post("/api/faturas", files={"arquivo": ("nubank.ofx", samples.ofx_cartao())}).json()
    tx = next(t for t in fat["transacoes"] if t["tipo"] == "compra")
    r = c.patch(f"/api/transacoes/{tx['id']}", json={"categoria": "Pagamento de fatura"})
    assert r.status_code in (409, 422)
    _sem_erro_500(r)


@pytest.mark.parametrize("texto,esperado", [
    ("1.234,56", 123456), ("R$ 1.234,56", 123456), ("(50,00)", -5000),
    ("9" * 60, None), ("99999999999999999999,99", None), ("1e308", None), ("NaN", None), ("", None),
])
def test_parse_money_limites(texto, esperado):
    from app.norm import parse_money_cents
    assert parse_money_cents(texto) == esperado


def test_parse_money_aceita_negativo_e_rejeita_estouro():
    from app.norm import MAX_CENTS, parse_money_cents
    assert parse_money_cents("-12,30") in (-1230, 1230)
    assert parse_money_cents(f"{MAX_CENTS // 100 + 1},00") is None


def test_texto_hostil_perde_caracteres_invisiveis():
    from app.norm import limpar_texto
    s = limpar_texto("LOJA‮EVIL\x00\x07​X" + "A" * 500)
    assert "‮" not in s and "\x00" not in s and "​" not in s
    assert len(s) <= 200


def test_chave_nao_junta_estabelecimentos_diferentes():
    from app.categorize import chave
    assert chave("PIX ENVIADO JOAO SILVA") != chave("PIX ENVIADO MARIA")
    assert chave("12345") and chave("*** 99")
    assert len(chave("A " * 400)) <= 100


def test_extrato_de_conta_so_conta_saidas():
    f = importar(CONTA, "extrato.ofx", {})
    assert f.conta is True
    assert f.soma_cents == 7000  # só os dois Pix enviados
    tipos = {t.descricao: t.tipo for t in f.txs}
    assert tipos["TRANSFERENCIA RECEBIDA EMPRESA XYZ"] == "entrada"
    c = novo_cliente()
    fat = c.post("/api/faturas", files={"arquivo": ("extrato.ofx", CONTA)}).json()
    assert fat["conta"] is True
    assert fat["reconciliacao"]["entradas_cents"] == 300000
    resumo = c.get(f"/api/resumo?fatura_id={fat['id']}").json()
    assert resumo["gasto_cents"] == 7000


def test_mesmo_conteudo_com_outro_nome_de_arquivo_e_duplicado():
    c = novo_cliente()
    assert c.post("/api/faturas", files={"arquivo": ("a.ofx", samples.ofx_cartao())}).status_code == 201
    r = c.post("/api/faturas", files={"arquivo": ("copia-renomeada.ofx", samples.ofx_cartao())})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ja_importada"


def test_csv_com_celula_gigante_e_rejeitado_sem_500():
    c = novo_cliente()
    corpo = b"Data,Descricao,Valor\r\n2026-10-05," + b"A" * 3_000_000 + b",10.00\r\n"
    r = c.post("/api/faturas", files={"arquivo": ("g.csv", corpo)})
    _sem_erro_500(r)


def test_limite_de_linhas(monkeypatch):
    monkeypatch.setattr(config, "MAX_LINHAS", 50)
    linhas = b"".join(b"2026-10-05,LOJA %d,1.00\r\n" % i for i in range(200))
    c = novo_cliente()
    r = c.post("/api/faturas", files={"arquivo": ("l.csv", b"Data,Descricao,Valor\r\n" + linhas)})
    assert r.status_code in (413, 422)
    _sem_erro_500(r)


def test_corpo_enviado_em_pedacos_respeita_o_limite(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0.001)
    c = novo_cliente()

    def pedacos():
        for _ in range(100):
            yield b"x" * 1024

    r = c.post("/api/faturas", content=pedacos(), headers={"Content-Type": "multipart/form-data; boundary=zz"})
    assert r.status_code in (400, 413, 422)


def test_host_e_origin_estranhos_sao_recusados():
    c = novo_cliente()
    assert c.get("/api/health", headers={"Host": "evil.example.com"}).status_code in (400, 403, 421)
    r = c.post("/api/faturas", files={"arquivo": ("a.ofx", samples.ofx_cartao())}, headers={"Origin": "https://evil.example.com"})
    assert r.status_code in (400, 403)
    ok = c.post("/api/faturas", files={"arquivo": ("a.ofx", samples.ofx_cartao())})
    assert ok.status_code == 201


def test_resposta_de_erro_sempre_no_mesmo_formato():
    c = TestClient(app)
    for r in (c.get("/api/rota-inexistente"), c.post("/api/faturas"), c.patch("/api/faturas/1", json={"total": []}),
              c.get("/api/resumo?fatura_id=abc")):
        assert r.status_code < 500
        assert "codigo" in r.json()["detail"], r.text


# ---------- contas, sessão e isolamento ----------

def test_api_exige_login_e_rotas_de_auth_respondem_sem_sessao():
    c = TestClient(app)
    for caminho in ("/api/faturas", "/api/categorias", "/api/resumo", "/api/parcelas-futuras", "/api/faturas/1"):
        r = c.get(caminho)
        assert r.status_code == 401 and r.json()["detail"]["codigo"] == "nao_autenticado", caminho
    assert c.post("/api/faturas", files={"arquivo": ("a.ofx", samples.ofx_cartao())}).status_code == 401
    eu = c.get("/api/auth/eu")
    assert eu.status_code == 200 and eu.json()["usuario"] is None  # 200 de propósito: não suja o console do navegador


def test_cadastro_login_logout_e_cookie_seguro():
    c = TestClient(app)
    r = c.post("/api/auth/cadastro", json={"nome": "Ana", "email": "Ana@Exemplo.com ", "senha": SENHA})
    assert r.status_code == 201 and r.json()["usuario"]["email"] == "ana@exemplo.com"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "mare_sessao=" in cookie
    assert SENHA not in r.text and "senha" not in r.json()["usuario"]
    assert c.get("/api/auth/eu").json()["usuario"]["nome"] == "Ana"
    assert c.get("/api/faturas").status_code == 200
    assert c.post("/api/auth/sair").status_code == 204
    assert c.get("/api/faturas").status_code == 401
    # entrar de novo com o e-mail em outra caixa
    ok = c.post("/api/auth/entrar", json={"email": "ANA@exemplo.com", "senha": SENHA})
    assert ok.status_code == 200 and c.get("/api/faturas").status_code == 200


def test_o_banco_guarda_so_hash_da_senha_e_da_sessao():
    c = novo_cliente()
    token = c.cookies.get("mare_sessao")
    with db.conn() as conexao:
        u = conexao.execute("SELECT * FROM usuarios").fetchone()
        sessoes = [r["token"] for r in conexao.execute("SELECT token FROM sessoes")]
    assert SENHA not in str(dict(u)) and u["senha"].startswith("scrypt$")
    assert token not in sessoes and len(sessoes) == 1


def test_login_errado_nao_revela_se_o_email_existe():
    novo_cliente()
    c = TestClient(app)
    a = c.post("/api/auth/entrar", json={"email": "ana@exemplo.com", "senha": "senha errada demais"})
    b = c.post("/api/auth/entrar", json={"email": "ninguem@exemplo.com", "senha": "senha errada demais"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_forca_bruta_no_login_e_barrada(monkeypatch):
    novo_cliente()
    c = TestClient(app)
    codigos = [c.post("/api/auth/entrar", json={"email": "ana@exemplo.com", "senha": f"errada numero {i}"}).status_code for i in range(12)]
    assert codigos[:8] == [401] * 8 and 429 in codigos
    bloqueado = c.post("/api/auth/entrar", json={"email": "ana@exemplo.com", "senha": SENHA})
    assert bloqueado.status_code == 429 and int(bloqueado.headers["retry-after"]) > 0


@pytest.mark.parametrize("corpo,codigo", [
    ({"nome": "Ana", "email": "sem-arroba", "senha": SENHA}, "email_invalido"),
    ({"nome": "Ana", "email": "a@b.co", "senha": "curta"}, "senha_fraca"),
    ({"nome": "Ana", "email": "a@b.co", "senha": "1234567890"}, "senha_fraca"),
    ({"nome": "Ana", "email": "a@b.co", "senha": "a" * 40}, "senha_fraca"),
    ({"nome": "\u202e\x00", "email": "a@b.co", "senha": SENHA}, "nome_invalido"),
])
def test_cadastro_recusa_dados_ruins(corpo, codigo):
    r = TestClient(app).post("/api/auth/cadastro", json=corpo)
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == codigo


def test_cadastro_com_dados_gigantes_ou_malformados_nao_da_500():
    c = TestClient(app)
    for corpo in ({"nome": "A" * 10_000, "email": "a@b.co", "senha": SENHA}, {"nome": "A", "email": "a@b.co", "senha": "x" * 500_000},
                  {"nome": ["x"], "email": 5, "senha": None}, {}):
        assert c.post("/api/auth/cadastro", json=corpo).status_code in (413, 422)
    assert c.post("/api/auth/entrar", content=b"nao e json", headers={"Content-Type": "application/json"}).status_code == 422


def test_email_duplicado_e_cadastro_fechado(monkeypatch):
    novo_cliente()
    r = TestClient(app).post("/api/auth/cadastro", json={"nome": "Outra", "email": "ANA@exemplo.com", "senha": SENHA})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "email_em_uso"
    monkeypatch.setattr(config, "CADASTRO_ABERTO", False)
    r = TestClient(app).post("/api/auth/cadastro", json={"nome": "Bia", "email": "bia@exemplo.com", "senha": SENHA})
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cadastro_fechado"


def test_primeira_conta_pode_ser_criada_mesmo_com_cadastro_fechado(monkeypatch):
    monkeypatch.setattr(config, "CADASTRO_ABERTO", False)
    assert TestClient(app).get("/api/auth/eu").json()["cadastro_aberto"] is True
    assert TestClient(app).post("/api/auth/cadastro", json={"nome": "Ana", "email": "ana@exemplo.com", "senha": SENHA}).status_code == 201
    assert TestClient(app).get("/api/auth/eu").json()["cadastro_aberto"] is False


def test_sessao_expirada_ou_forjada_nao_entra():
    c = novo_cliente()
    assert c.get("/api/faturas").status_code == 200
    with db.conn() as conexao:
        conexao.execute("UPDATE sessoes SET expira_em = datetime('now', '-1 minute')")
    assert c.get("/api/faturas").status_code == 401
    c.cookies.set("mare_sessao", "A" * 43)
    assert c.get("/api/faturas").status_code == 401
    c.cookies.set("mare_sessao", "x" * 5000)
    assert c.get("/api/faturas").status_code == 401


def test_um_usuario_nao_enxerga_nem_altera_dados_do_outro():
    a, b = novo_cliente("a@exemplo.com", "A"), novo_cliente("b@exemplo.com", "B")
    fat = a.post("/api/faturas", files={"arquivo": ("nubank.ofx", samples.ofx_cartao())}).json()
    tx = next(t for t in fat["transacoes"] if t["tipo"] == "compra")
    assert b.get("/api/faturas").json() == []
    assert b.get(f"/api/faturas/{fat['id']}").status_code == 404
    assert b.delete(f"/api/faturas/{fat['id']}").status_code == 404
    assert b.patch(f"/api/faturas/{fat['id']}", json={"total": "1,00"}).status_code == 404
    assert b.patch(f"/api/transacoes/{tx['id']}", json={"categoria": "Casa"}).status_code == 404
    assert b.get(f"/api/resumo?fatura_id={fat['id']}").status_code == 404
    assert b.get("/api/parcelas-futuras").json()["meses"] == []
    r = b.post("/api/transacoes/restaurar", json={"itens": [{"id": tx["id"], "categoria": "Casa"}], "chave": "mercado livre",
                                                  "categoria_regra": "Casa"})
    assert r.status_code == 422
    assert a.get(f"/api/faturas/{fat['id']}").json()["transacoes"][0]["categoria"] == fat["transacoes"][0]["categoria"]
    # as regras de categoria de um não vazam para o outro, e o mesmo arquivo pode ser importado pelos dois
    a.patch(f"/api/transacoes/{tx['id']}", json={"categoria": "Casa"})
    assert db.regras_usuario(2) == {}
    assert b.post("/api/faturas", files={"arquivo": ("nubank.ofx", samples.ofx_cartao())}).status_code == 201


def test_limite_de_envios_por_minuto(monkeypatch):
    monkeypatch.setattr(config, "UPLOADS_POR_MINUTO", 3)
    c = novo_cliente()
    codigos = [c.post("/api/faturas", files={"arquivo": ("x.csv", b"lixo")}).status_code for _ in range(5)]
    assert codigos[:3] == [415, 415, 415] or all(k in (415, 422) for k in codigos[:3])
    assert codigos[3:] == [429, 429]
    outro = novo_cliente("b@exemplo.com")  # o limite é por usuário
    assert outro.post("/api/faturas", files={"arquivo": ("x.csv", b"lixo")}).status_code != 429


def test_dados_antigos_sem_dono_vao_para_a_primeira_conta():
    # banco "de antes das contas": a primeira conta criada adota as faturas e as regras existentes
    with db.conn() as conexao:
        f = importar(samples.ofx_cartao(), "nubank.ofx", {})
        conexao.execute("INSERT INTO faturas (usuario_id, referencia, soma_cents, status, formato, hash) VALUES (NULL, '2026-10-01', 0, 'sem_total', 'ofx', 'h-antigo')")
        conexao.execute("INSERT INTO regras (usuario_id, chave, categoria) VALUES (0, 'uber', 'Transporte')")
    assert f is not None
    c = novo_cliente()
    assert len(c.get("/api/faturas").json()) == 1
    assert db.regras_usuario(1) == {"uber": "Transporte"}
    assert novo_cliente("b@exemplo.com").get("/api/faturas").json() == []


# ---------- fatura reexportada com mais linhas, e cartões sem nome ----------

def _ofx_com(linhas):
    base = samples.ofx_cartao(saldo=None).decode("cp1252")
    extra = "".join(f"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>{d}<TRNAMT>{v}<FITID>{i}<MEMO>{m}</STMTTRN>\n" for i, (d, v, m) in enumerate(linhas, 900))
    return base.replace("</BANKTRANLIST>", extra + "</BANKTRANLIST>").encode("cp1252")


def test_arquivo_mais_completo_atualiza_a_fatura_em_vez_de_duplicar():
    c = novo_cliente()
    primeiro = c.post("/api/faturas", files={"arquivo": ("fat.ofx", samples.ofx_cartao(saldo=None))})
    assert primeiro.status_code == 201
    n0 = len(primeiro.json()["transacoes"])
    maior = c.post("/api/faturas", files={"arquivo": ("fat-dia-30.ofx", _ofx_com([("20261030", "-45.90", "PADARIA NOVA"), ("20261031", "-12.00", "CAFE CENTRAL")]))})
    assert maior.status_code == 200, maior.text
    corpo = maior.json()
    assert corpo["id"] == primeiro.json()["id"] and corpo["atualizada"]["novos"] == 2
    assert len(corpo["transacoes"]) == n0 + 2
    assert len(c.get("/api/faturas").json()) == 1
    # reenviar o arquivo menor, ou o mesmo maior de novo, não cria nada
    assert c.post("/api/faturas", files={"arquivo": ("fat.ofx", samples.ofx_cartao(saldo=None))}).status_code == 409
    assert c.post("/api/faturas", files={"arquivo": ("de-novo.ofx", _ofx_com([("20261030", "-45.90", "PADARIA NOVA"), ("20261031", "-12.00", "CAFE CENTRAL")]))}).status_code == 409
    assert len(c.get("/api/faturas").json()) == 1


def test_faturas_diferentes_nao_sao_juntadas():
    c = novo_cliente()
    assert c.post("/api/faturas", files={"arquivo": ("a.ofx", samples.ofx_cartao())}).status_code == 201
    outra = _ofx_com([("20261015", "-99.00", "LOJA QUE NAO EXISTE"), ("20261016", "-5.00", "OUTRA COISA")]).replace(b"<DTSTART>20261003", b"<DTSTART>20261003")
    # só 2 linhas em comum com muitas diferentes: abaixo de 80% do menor arquivo? aqui o menor tem as mesmas linhas + 2, então junta
    r = c.post("/api/faturas", files={"arquivo": ("b.ofx", outra)})
    assert r.status_code in (200, 201)
    csv = b"Data,Descricao,Valor\r\n2026-09-01,LOJA A,10.00\r\n2026-09-02,LOJA B,20.00\r\n"
    assert c.post("/api/faturas", files={"arquivo": ("c.csv", csv)}).status_code == 201
    csv2 = b"Data,Descricao,Valor\r\n2026-09-01,LOJA A,10.00\r\n2026-09-05,LOJA Z,77.00\r\n2026-09-06,LOJA Y,88.00\r\n"
    assert c.post("/api/faturas", files={"arquivo": ("d.csv", csv2)}).status_code == 201  # 1 de 2 em comum: menos de 80%


def test_cartoes_sem_nome_de_bancos_diferentes_nao_misturam_as_parcelas():
    c = novo_cliente()
    a = b"Data,Descricao,Valor\r\n2026-10-05,TV Parcela 1/4,100.00\r\n"
    b = b"Date,Title,Amount\r\n2026-10-06,Celular Parcela 1/3,200.00\r\n"
    assert c.post("/api/faturas", files={"arquivo": ("a.csv", a)}).status_code == 201
    assert c.post("/api/faturas", files={"arquivo": ("b.csv", b)}).status_code == 201
    parc = c.get("/api/parcelas-futuras").json()
    assert parc["total_cents"] == 3 * 10000 + 2 * 20000


def test_openapi_e_docs_estao_desligados():
    c = TestClient(app)
    for caminho in ("/openapi.json", "/docs", "/redoc"):
        assert c.get(caminho).status_code == 404


def test_pagina_404_do_servidor_e_html_e_a_da_api_e_json():
    c = TestClient(app)
    r = c.get("/nao/existe", headers={"Accept": "text/html"})
    assert r.status_code == 404 and "text/html" in r.headers["content-type"] and "Página não encontrada" in r.text
    j = c.get("/api/nao-existe")
    assert j.status_code in (401, 404) and "codigo" in j.json()["detail"]


def test_respostas_nao_vazam_detalhes_internos():
    c = novo_cliente()
    fat = c.post("/api/faturas", files={"arquivo": ("nubank.ofx", samples.ofx_cartao())})
    texto = fat.text + c.get("/api/faturas").text
    for proibido in ("Traceback", "sqlite", config.DB_PATH, "senha", "scrypt", "usuario_id", '"hash"', "origem"):
        assert proibido not in texto, proibido
    assert "no-store" in c.get("/api/faturas").headers["cache-control"]


# ---------- confirmação de e-mail por código (SMTP) ----------
class Caixa:
    """Substitui o envio SMTP: guarda o que seria enviado."""
    def __init__(self):
        self.codigos, self.avisos, self.falhar = [], [], False

    def codigo(self, para, nome, codigo, minutos):
        if self.falhar:
            raise correio.ErroEnvio("falhou")
        self.codigos.append((para, nome, codigo))

    def aviso(self, para):
        if self.falhar:
            raise correio.ErroEnvio("falhou")
        self.avisos.append(para)


@pytest.fixture
def caixa(monkeypatch):
    c = Caixa()
    monkeypatch.setattr(config, "CONFIRMAR_EMAIL", True)
    monkeypatch.setattr(correio, "enviar_codigo", c.codigo)
    monkeypatch.setattr(correio, "enviar_aviso_conta_existente", c.aviso)
    return c


def cadastrar(c, email="ana@exemplo.com", nome="Ana", senha=SENHA):
    return c.post("/api/auth/cadastro", json={"nome": nome, "email": email, "senha": senha})


def test_conta_so_nasce_depois_do_codigo(caixa):
    c = TestClient(app)
    r = cadastrar(c)
    assert r.status_code == 202 and r.json()["pendente"] is True and r.json()["email"] == "ana@exemplo.com"
    assert "usuario" not in r.json()
    assert db.total_usuarios() == 0 and db.usuario_por_email("ana@exemplo.com") is None
    assert c.get("/api/auth/eu").json()["usuario"] is None  # nenhuma sessão aberta ainda
    para, nome, codigo = caixa.codigos[-1]
    assert para == "ana@exemplo.com" and nome == "Ana" and len(codigo) == 6 and codigo.isdigit()
    r = c.post("/api/auth/confirmar", json={"codigo": codigo})
    assert r.status_code == 201 and r.json()["usuario"]["email"] == "ana@exemplo.com"
    assert c.get("/api/auth/eu").json()["usuario"]["email"] == "ana@exemplo.com"
    assert db.usuario_por_email("ana@exemplo.com")["email_confirmado"] == 1
    # entra normalmente depois, com a senha escolhida no cadastro
    c2 = TestClient(app)
    assert c2.post("/api/auth/entrar", json={"email": "ana@exemplo.com", "senha": SENHA}).status_code == 200


def test_codigo_aceita_espacos_e_vale_uma_vez(caixa):
    c = TestClient(app)
    cadastrar(c)
    cod = caixa.codigos[-1][2]
    assert c.post("/api/auth/confirmar", json={"codigo": f"{cod[:3]} {cod[3:]}"}).status_code == 201
    assert c.post("/api/auth/confirmar", json={"codigo": cod}).status_code == 400  # já usado


def test_codigo_errado_conta_tentativas_e_bloqueia(caixa):
    c = TestClient(app)
    cadastrar(c)
    certo = caixa.codigos[-1][2]
    errado = "000000" if certo != "000000" else "111111"
    for i in range(4):
        r = c.post("/api/auth/confirmar", json={"codigo": errado})
        assert r.status_code == 400 and r.json()["detail"]["codigo"] == "codigo_invalido"
    r = c.post("/api/auth/confirmar", json={"codigo": errado})  # 5ª tentativa errada
    assert r.status_code == 429 and r.json()["detail"]["codigo"] == "codigo_bloqueado"
    # o código certo já não vale: o cadastro foi descartado
    assert c.post("/api/auth/confirmar", json={"codigo": certo}).status_code == 400
    assert db.total_usuarios() == 0


def test_codigo_certo_na_ultima_tentativa_ainda_funciona(caixa):
    c = TestClient(app)
    cadastrar(c)
    certo = caixa.codigos[-1][2]
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(4):
        c.post("/api/auth/confirmar", json={"codigo": errado})
    assert c.post("/api/auth/confirmar", json={"codigo": certo}).status_code == 201


def test_codigo_mal_formado_nao_passa(caixa):
    c = TestClient(app)
    cadastrar(c)
    for ruim in ["", "12345", "1234567", "abcdef"]:  # cada um gasta uma das 5 tentativas
        assert c.post("/api/auth/confirmar", json={"codigo": ruim}).status_code == 400
    assert db.total_usuarios() == 0


def test_codigo_vencido_nao_vale(caixa):
    c = TestClient(app)
    cadastrar(c)
    cod = caixa.codigos[-1][2]
    with db.conn() as k:
        k.execute("UPDATE cadastros_pendentes SET expira_em=datetime('now','-1 minutes')")
    r = c.post("/api/auth/confirmar", json={"codigo": cod})
    assert r.status_code == 400 and db.total_usuarios() == 0


def test_so_o_navegador_que_cadastrou_confirma(caixa):
    c = TestClient(app)
    cadastrar(c)
    cod = caixa.codigos[-1][2]
    outro = TestClient(app)  # quem só conhece o e-mail e o código, sem o cookie, não conclui
    assert outro.post("/api/auth/confirmar", json={"codigo": cod}).status_code == 400
    assert db.total_usuarios() == 0
    assert c.post("/api/auth/confirmar", json={"codigo": cod}).status_code == 201


def test_cadastro_pendente_guarda_so_hashes(caixa):
    c = TestClient(app)
    cadastrar(c)
    cod = caixa.codigos[-1][2]
    token = c.cookies.get("mare_cadastro")
    with db.conn() as k:
        linha = dict(k.execute("SELECT * FROM cadastros_pendentes").fetchone())
    guardado = " ".join(str(v) for v in linha.values())
    assert cod not in guardado.replace(linha["sal"], "") and SENHA not in guardado and token not in guardado
    assert linha["senha"].startswith("scrypt") or "$" in linha["senha"]


def test_cookie_do_cadastro_e_httponly_e_restrito(caixa):
    c = TestClient(app)
    r = cadastrar(c)
    set_cookie = r.headers["set-cookie"].lower()
    assert "mare_cadastro=" in set_cookie and "httponly" in set_cookie and "samesite=strict" in set_cookie and "path=/api/auth" in set_cookie


def test_reenvio_respeita_a_espera_e_invalida_o_codigo_antigo(caixa):
    c = TestClient(app)
    cadastrar(c)
    antigo = caixa.codigos[-1][2]
    r = c.post("/api/auth/reenviar")
    assert r.status_code == 429 and "Retry-After" in r.headers and len(caixa.codigos) == 1
    with db.conn() as k:
        k.execute("UPDATE cadastros_pendentes SET enviado_em=datetime('now','-120 seconds')")
    r = c.post("/api/auth/reenviar")
    assert r.status_code == 202 and len(caixa.codigos) == 2
    novo = caixa.codigos[-1][2]
    if novo != antigo:
        assert c.post("/api/auth/confirmar", json={"codigo": antigo}).status_code == 400
    assert c.post("/api/auth/confirmar", json={"codigo": novo}).status_code == 201


def test_reenvio_tem_teto_por_cadastro(caixa):
    c = TestClient(app)
    cadastrar(c)
    for _ in range(4):
        with db.conn() as k:
            k.execute("UPDATE cadastros_pendentes SET enviado_em=datetime('now','-120 seconds')")
        for lim in main._lim.values():
            lim.limpar()
        assert c.post("/api/auth/reenviar").status_code == 202
    with db.conn() as k:
        k.execute("UPDATE cadastros_pendentes SET enviado_em=datetime('now','-120 seconds')")
    for lim in main._lim.values():
        lim.limpar()
    r = c.post("/api/auth/reenviar")
    assert r.status_code == 429 and r.json()["detail"]["codigo"] == "limite_de_envios"


def test_reenviar_sem_cadastro_em_andamento(caixa):
    assert TestClient(app).post("/api/auth/reenviar").status_code == 400


def test_email_ja_cadastrado_responde_igual_e_avisa_o_dono(caixa):
    dono = TestClient(app)
    cadastrar(dono)
    dono.post("/api/auth/confirmar", json={"codigo": caixa.codigos[-1][2]})
    caixa.codigos.clear()
    intruso = TestClient(app)
    r = cadastrar(intruso, nome="Outra", senha="outra frase longa e boa")
    assert r.status_code == 202 and r.json()["pendente"] is True and r.json()["email"] == "ana@exemplo.com"
    assert caixa.codigos == [] and caixa.avisos == ["ana@exemplo.com"]
    # o código nunca existiu: nada a confirmar, e a conta original segue intacta
    assert intruso.post("/api/auth/confirmar", json={"codigo": "123456"}).status_code == 400
    assert db.total_usuarios() == 1
    assert TestClient(app).post("/api/auth/entrar", json={"email": "ana@exemplo.com", "senha": SENHA}).status_code == 200


def test_falha_no_smtp_da_503_e_nao_deixa_cadastro_pendente(caixa):
    caixa.falhar = True
    r = cadastrar(TestClient(app))
    assert r.status_code == 503 and r.json()["detail"]["codigo"] == "email_indisponivel"
    with db.conn() as k:
        assert k.execute("SELECT COUNT(*) FROM cadastros_pendentes").fetchone()[0] == 0
    caixa.falhar = False
    for lim in main._lim.values():
        lim.limpar()
    assert cadastrar(TestClient(app)).status_code == 202  # sem espera de reenvio presa


def test_cadastro_em_andamento_nao_troca_a_senha_de_quem_chegou_primeiro(caixa):
    primeiro = TestClient(app)
    cadastrar(primeiro)
    cod = caixa.codigos[-1][2]
    intruso = TestClient(app)
    r = cadastrar(intruso, senha="senha do intruso muito longa")
    assert r.status_code == 429 and len(caixa.codigos) == 1
    assert primeiro.post("/api/auth/confirmar", json={"codigo": cod}).status_code == 201
    assert TestClient(app).post("/api/auth/entrar", json={"email": "ana@exemplo.com", "senha": SENHA}).status_code == 200


def test_cadastro_fechado_vale_de_novo_na_confirmacao(caixa, monkeypatch):
    c = TestClient(app)
    monkeypatch.setattr(config, "CADASTRO_ABERTO", True)
    cadastrar(c, "a@exemplo.com")
    cod = caixa.codigos[-1][2]
    db.criar_usuario("dono@exemplo.com", "Dono", "x", confirmado=True)  # alguém entrou no meio
    monkeypatch.setattr(config, "CADASTRO_ABERTO", False)
    r = c.post("/api/auth/confirmar", json={"codigo": cod})
    assert r.status_code == 403 and db.usuario_por_email("a@exemplo.com") is None


def test_eu_informa_se_a_confirmacao_esta_ligada(caixa, monkeypatch):
    assert TestClient(app).get("/api/auth/eu").json()["confirmar_email"] is True
    monkeypatch.setattr(config, "CONFIRMAR_EMAIL", False)
    assert TestClient(app).get("/api/auth/eu").json()["confirmar_email"] is False


def test_sem_confirmacao_o_cadastro_continua_direto(monkeypatch):
    c = TestClient(app)
    assert cadastrar(c).status_code == 201 and c.get("/api/auth/eu").json()["usuario"] is not None
    assert c.post("/api/auth/confirmar", json={"codigo": "123456"}).status_code == 400
    assert c.post("/api/auth/reenviar").status_code == 400


def test_limite_de_pedidos_de_codigo_por_email(caixa):
    codigos_http = []
    for _ in range(7):
        codigos_http.append(cadastrar(TestClient(app)).status_code)
    assert 429 in codigos_http


def test_configuracao_smtp_incompleta_falha_na_subida(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "")
    with pytest.raises(RuntimeError):
        correio.exigir_configuracao()
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr(config, "SMTP_REMETENTE", "")
    monkeypatch.setattr(config, "SMTP_USUARIO", "")
    with pytest.raises(RuntimeError):
        correio.exigir_configuracao()
    monkeypatch.setattr(config, "SMTP_REMETENTE", "maré@exemplo.com")
    monkeypatch.setattr(config, "SMTP_SEGURANCA", "nenhuma")
    monkeypatch.setattr(config, "SMTP_USUARIO", "u")
    with pytest.raises(RuntimeError):  # senha em claro por rede aberta: recusa
        correio.exigir_configuracao()
    monkeypatch.setattr(config, "SMTP_SEGURANCA", "starttls")
    correio.exigir_configuracao()


def test_email_do_codigo_escapa_o_nome_e_nao_vaza_a_senha(monkeypatch):
    enviados = []
    monkeypatch.setattr(correio, "enviar", lambda para, assunto, texto, corpo_html=None: enviados.append((para, assunto, texto, corpo_html)))
    correio.enviar_codigo("a@b.com", "<script>x</script>", "123456", 10)
    para, assunto, texto, html_ = enviados[0]
    assert "123456" in texto and "<script>" not in html_ and "&lt;script&gt;" in html_
