"""tools/anonimizar.py: troca dados pessoais sem estragar o que o teste precisa conferir (datas, valores, tipos).
Todos os nomes, CPFs e contas daqui são fictícios."""
import re
from collections import Counter

from app.pipeline import importar
from tests import samples
from tests.test_app import _ofx_com
from tools import anonimizar as an

# Só dados inventados: nada daqui existe.
MARIA = ("Transferência enviada pelo Pix - MARIA FICTICIA DA SILVA - •••.123.456-•• - "
         "BCO TESTE S.A. (0001) Agência: 1234 Conta: 56789-0")
LOJA = ("Transferência enviada pelo Pix - LOJA EXEMPLO LTDA - 11.222.333/0001-44 - "
        "BCO TESTE S.A. (0001) Agência: 4321 Conta: 98765-4")
RECEBIDO = ("Transferência Recebida - Maria Ficticia da Silva - •••.123.456-•• - "
            "BCO TESTE S.A. (0001) Agência: 1234 Conta: 56789-0")
CRU_PROIBIDO = ("MARIA", "Maria Ficticia", "123.456", "11.222.333", "1234", "56789", "98765", "5544332211", "joao@exemplo.org",
                "12345678901", "99999-8888")


def _ofx_cru() -> bytes:
    """OFX de teste com Pix para pessoa e para empresa, e o número da conta no cabeçalho (tudo inventado)."""
    extra = [("20261030", "-45.00", MARIA), ("20261029", "-80.00", LOJA), ("20261028", "250.00", RECEBIDO),
             ("20261027", "-12.00", "Pix enviado 12345678901 JOAO para joao@exemplo.org, tel (11) 99999-8888")]
    return _ofx_com(extra).replace(b"<ACCTID>0000", b"<ACCTID>5544332211")


def _chaves(f):
    return Counter((t.data.isoformat(), t.bruto_cents) for t in f.txs)


def test_ofx_anonimizado_nao_tem_mais_dado_pessoal_e_continua_igual_para_o_teste():
    cru = _ofx_cru()
    texto = cru.decode("cp1252")
    novo, rel = an.anonimizar(texto)
    assert an.achados(novo) == []
    for proibido in CRU_PROIBIDO:
        assert proibido not in novo, proibido
    # datas, valores e soma ficam idênticos: é o que o teste confere
    antes, depois = importar(cru, "a.ofx", {}), importar(novo.encode("cp1252"), "b.ofx", {})
    assert _chaves(antes) == _chaves(depois) and antes.soma_cents == depois.soma_cents
    assert antes.status == depois.status and antes.total_cents == depois.total_cents
    assert rel.contagem["nomes de pessoas"] == 2 and len(rel.nomes) == 1  # a mesma pessoa vira o mesmo apelido


def test_empresa_com_cnpj_mantem_o_nome_e_pessoa_vira_apelido():
    novo, _ = an.anonimizar(_ofx_cru().decode("cp1252"))
    assert "LOJA EXEMPLO LTDA - 00.000.000/0000-00" in novo
    assert "PESSOA 01 - 000.000.000-00" in novo
    assert "Agência: 0000 Conta: 00000-0" in novo


def test_ids_do_ofx_sao_zerados_e_fitid_continua_unico():
    novo, _ = an.anonimizar(_ofx_cru().decode("cp1252"))
    assert "<ACCTID>0000000000" in novo
    fitids = re.findall(r"<FITID>([^<\r\n]*)", novo)
    assert len(fitids) == len(set(fitids)) > 5 and all(f.startswith("ANON") for f in fitids)
    # datas e valores do OFX não são tocados (14 dígitos de data não são CNPJ)
    assert "<DTPOSTED>20261005120000[-3:BRT]" in novo and "<TRNAMT>-45.90" in novo


def test_anonimizar_e_idempotente():
    texto = _ofx_cru().decode("cp1252")
    uma, _ = an.anonimizar(texto)
    duas, _ = an.anonimizar(uma)
    assert uma == duas


def test_csv_tambem_e_anonimizado_e_continua_valendo():
    csv = ("Data,Valor,Identificador,Descrição\n"
           f"31/10/2026,-45.00,id1,{MARIA}\n"
           f"18/10/2026,-80.00,id2,{LOJA}\n"
           "28/10/2026,-33.00,id3,Compra no débito - FACEBURGUER DELIVERY\n"
           f"20/10/2026,2000.00,id4,{RECEBIDO}\n")
    novo, _ = an.anonimizar(csv)
    assert an.achados(novo) == []
    for proibido in ("MARIA", "123.456", "56789", "98765"):
        assert proibido not in novo
    assert "FACEBURGUER DELIVERY" in novo and "-33.00" in novo
    a, b = importar(csv.encode(), "a.csv", {}), importar(novo.encode(), "b.csv", {})
    assert _chaves(a) == _chaves(b)


def test_achados_aponta_a_linha_sem_mostrar_o_conteudo():
    ruins = an.achados("linha ok\nPix - MARIA - 123.456.789-09 - banco\nAgência: 1234 Conta: 56789-0\n")
    assert [n for n, _ in ruins] == [2, 3, 3]
    assert {t for _, t in ruins} == {"CPF/CNPJ", "agência", "conta"}


def test_sem_nada_a_trocar_o_texto_nao_muda():
    csv = "Data,Valor,Descricao\n2026-09-01,10.00,LOJA A\n2026-09-02,20.00,LOJA B\n"
    novo, rel = an.anonimizar(csv)
    assert novo == csv and not rel.contagem


# ---------- linha de comando ----------

def _escreve(tmp_path, nome="fatura.ofx"):
    origem = tmp_path / "_originais" / nome
    origem.parent.mkdir(parents=True, exist_ok=True)
    origem.write_bytes(_ofx_cru())
    return origem


def test_cli_escreve_o_resultado_e_nao_imprime_o_dado_original(tmp_path, capsys):
    origem = _escreve(tmp_path)
    destino = tmp_path / "bancos" / "nubank-conta.ofx"
    assert an.main([str(origem), str(destino)]) == 0
    saida = capsys.readouterr().out
    for proibido in CRU_PROIBIDO:
        assert proibido not in saida, proibido
    assert "PESSOA 01" in saida  # a conferência mostra as descrições já anonimizadas
    novo = destino.read_bytes()
    assert b"MARIA" not in novo and b"5544332211" not in novo
    assert importar(novo, "x.ofx", {}).soma_cents == importar(origem.read_bytes(), "y.ofx", {}).soma_cents


def test_cli_recusa_destino_perigoso(tmp_path, capsys):
    origem = _escreve(tmp_path)
    assert an.main([str(origem), str(origem)]) == 2                                    # sobrescreveria o original
    assert an.main([str(origem), str(tmp_path / "_originais" / "saida.ofx")]) == 2    # pasta dos crus
    assert an.main([str(origem), str(tmp_path / "NU_5544332211_01OUT2026.ofx")]) == 2  # número da conta no nome
    assert an.main([str(tmp_path / "nao-existe.ofx"), str(tmp_path / "x.ofx")]) == 2
    ok = tmp_path / "bancos" / "a.ofx"
    assert an.main([str(origem), str(ok)]) == 0
    assert an.main([str(origem), str(ok)]) == 2                                        # já existe
    assert an.main([str(origem), str(ok), "--sobrescrever"]) == 0


def test_rodar_de_novo_nao_troca_os_apelidos_de_lugar():
    # duas pessoas, e a segunda aparece antes: na 2ª passada PESSOA 02 não pode virar PESSOA 01
    txt = ("Pix - ZELIA INVENTADA - 111.222.333-44 - BANCO X\n"
           "Pix - ARTUR INVENTADO - 555.666.777-88 - BANCO Y\n"
           "Pix - ZELIA INVENTADA - 111.222.333-44 - BANCO X\n")
    uma, _ = an.anonimizar(txt)
    assert uma.splitlines()[0].startswith("Pix - PESSOA 01") and uma.splitlines()[1].startswith("Pix - PESSOA 02")
    ordem_invertida = "\n".join(reversed(uma.splitlines()))
    duas, _ = an.anonimizar(ordem_invertida)
    assert duas == ordem_invertida


# ---------- modo genérico: nomes locais viram nomes genéricos da mesma categoria ----------

COOP = "CC CENTRO LESTE NORTE MARANHENSE - SICOOB CENTROLESTE Agência: 4321 Conta: 98765-4"
PIZZARIA = f"Transferência enviada pelo Pix - PIZZARIA DO ZE DA ILHA - 11.222.333/0001-44 - {COOP}"
OFICINA = "Transferência enviada pelo Pix - AUTO PECAS DO MANOEL - 22.333.444/0001-55 - BCO BRADESCO S.A. (0237) Agência: 1111 Conta: 22222-3"
IGREJA = "Transferência enviada pelo Pix - IGREJA BATISTA DO ANGELIM - 33.444.555/0001-66 - BCO DO BRASIL S.A. (0001) Agência: 2222 Conta: 33333-4"
MARCA = "Transferência enviada pelo Pix - NETFLIX.COM LTDA - 44.555.666/0001-77 - ITAU UNIBANCO S.A. (0341) Agência: 3333 Conta: 44444-5"


def _ofx_locais() -> bytes:
    extra = [("20261030", "-60.00", PIZZARIA), ("20261029", "-90.00", OFICINA),
             ("20261028", "-50.00", IGREJA), ("20261027", "-39.90", MARCA)]
    return _ofx_com(extra)


def _categorias(f):
    return {(t.data.isoformat(), t.bruto_cents): t.categoria for t in f.txs}


def test_generico_tira_o_que_entrega_a_cidade_a_religiao_e_a_cooperativa():
    novo, rel = an.anonimizar(_ofx_locais().decode("cp1252"), generico=True)
    for local in ("PIZZARIA", "ZE DA ILHA", "MANOEL", "IGREJA", "BATISTA", "ANGELIM", "MARANHENSE", "SICOOB"):
        assert local not in novo, local
    assert "RESTAURANTE EXEMPLO 01" in novo and "AUTO PECAS EXEMPLO 01" in novo and "EMPRESA EXEMPLO 01" in novo
    assert "BANCO EXEMPLO" in novo                      # a cooperativa regional sumiu
    assert "NETFLIX.COM LTDA" in novo                   # marca conhecida fica
    assert "BCO DO BRASIL S.A. (0001)" in novo and "BCO BRADESCO S.A. (0237)" in novo  # banco grande fica
    assert an.achados(novo) == []
    assert rel.contagem["nomes de empresas"] == 3


def test_generico_mantem_categorias_datas_e_valores():
    cru = _ofx_locais()
    novo, _ = an.anonimizar(cru.decode("cp1252"), generico=True)
    antes, depois = importar(cru, "a.ofx", {}), importar(novo.encode("cp1252"), "b.ofx", {})
    assert _chaves(antes) == _chaves(depois) and antes.soma_cents == depois.soma_cents
    assert _categorias(antes) == _categorias(depois)    # o nome genérico cai na mesma categoria do original
    assert _categorias(depois)[("2026-10-30", -6000)] == "Alimentação"
    assert _categorias(depois)[("2026-10-29", -9000)] == "Transporte"


def test_generico_e_idempotente_e_o_modo_normal_nao_muda():
    texto = _ofx_locais().decode("cp1252")
    uma, _ = an.anonimizar(texto, generico=True)
    duas, _ = an.anonimizar(uma, generico=True)
    assert uma == duas
    normal, _ = an.anonimizar(texto)
    assert "PIZZARIA DO ZE DA ILHA" in normal           # sem a opção, empresas com CNPJ mantêm o nome


def test_cli_com_generico(tmp_path, capsys):
    origem = tmp_path / "_originais" / "x.ofx"
    origem.parent.mkdir()
    origem.write_bytes(_ofx_locais())
    destino = tmp_path / "bancos" / "teste-conta.ofx"
    assert an.main([str(origem), str(destino), "--generico"]) == 0
    saida = capsys.readouterr().out + destino.read_text(encoding="cp1252")
    for local in ("PIZZARIA", "MANOEL", "IGREJA", "MARANHENSE"):
        assert local not in saida, local
