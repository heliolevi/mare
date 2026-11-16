"""Um teste por arquivo real (já anonimizado) em tests/bancos/.

Cada arquivo `nome.ofx` ou `nome.csv` precisa de um `nome.esperado.json` ao lado, por exemplo:

    {"banco": "Nubank", "formato": "ofx", "conta": true, "status": "sem_total", "linhas": 40}

`status` é "ok" quando o arquivo traz o total e a soma bate ("Conferido"). Extratos de conta não têm total: "sem_total".
Se um banco mudar o formato de exportação (ou um ajuste quebrar a leitura), o teste daquele banco falha com o nome dele.
Como gerar o arquivo: tests/bancos/README.md."""
import json
from pathlib import Path

import pytest

from app.pipeline import importar

PASTA = Path(__file__).parent / "bancos"
ARQUIVOS = sorted(p for p in PASTA.glob("*") if p.suffix.lower() in (".ofx", ".qfx", ".csv"))


@pytest.mark.skipif(not ARQUIVOS, reason="ainda não há arquivo real em tests/bancos (veja o README da pasta)")
@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: p.name)
def test_arquivo_real_continua_sendo_lido_como_esperado(arquivo: Path):
    esperado_json = arquivo.with_suffix(".esperado.json")
    assert esperado_json.exists(), f"falta {esperado_json.name} ao lado de {arquivo.name}"
    esperado = json.loads(esperado_json.read_text(encoding="utf-8"))

    f = importar(arquivo.read_bytes(), arquivo.name, {})
    assert f.formato == esperado["formato"], "formato"
    assert f.conta == esperado["conta"], "conta ou cartão"
    assert f.status == esperado["status"], f"status ({esperado.get('banco', arquivo.name)} deixou de sair como esperado)"
    assert len(f.txs) == esperado["linhas"], "quantidade de lançamentos"
    if esperado.get("total_cents") is not None:
        assert f.total_cents == esperado["total_cents"] and f.soma_cents == esperado["total_cents"], "total e soma"
    assert all(t.descricao for t in f.txs), "nenhum lançamento pode ficar sem descrição"
