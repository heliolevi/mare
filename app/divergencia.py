"""Por que a soma não bate com o total? Sugere as causas mais prováveis em vez de só mostrar "Divergente".

Convenção: diferença = soma - total. A soma do app é compras + encargos + saldo anterior - estornos; pagamentos recebidos
ficam fora. Diferença positiva quer dizer que o app somou MAIS do que o banco; negativa, que somou MENOS.

Cada hipótese só aparece quando um valor do próprio arquivo bate exatamente com a diferença (tolerância de 1 centavo, a
mesma da conferência). Por isso o texto fala em "parece": é uma pista para a pessoa conferir no app do banco, não um
veredito. As causas vêm da mais específica para a mais genérica, e no máximo `limite` delas."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

TOLERANCIA = 1  # centavo, igual à da conferência (pipeline.interpretar)
GASTOS = ("compra", "encargo", "saldo_anterior")


@dataclass(frozen=True)
class Linha:
    data: str          # AAAA-MM-DD
    titulo: str
    valor_cents: int   # sempre positivo; o sinal vem do tipo
    tipo: str


def _brl(centavos: int) -> str:
    reais, cts = divmod(abs(centavos), 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{cts:02d}"


def _dm(iso: str) -> str:
    _, m, d = iso[:10].split("-")
    return f"{d}/{m}"


def _igual(a: int, b: int) -> bool:
    return abs(a - b) <= TOLERANCIA


def _lista(linhas: list[Linha], max_itens: int = 3) -> str:
    nomes = [f"{l.titulo} ({_dm(l.data)})" for l in linhas[:max_itens]]
    mais = len(linhas) - max_itens
    return ", ".join(nomes) + (f" e mais {mais}" if mais > 0 else "")


def explicar(linhas: list[Linha], total_cents: int | None, soma_cents: int, limite: int = 3) -> list[dict[str, str]]:
    """Causas prováveis da divergência, como [{"codigo": ..., "texto": ...}]. Vazio se não houver divergência."""
    if total_cents is None:
        return []
    d = soma_cents - total_cents
    a = abs(d)
    if a <= TOLERANCIA:
        return []
    mais = d > 0  # o app somou mais do que o banco

    por_tipo: dict[str, list[Linha]] = defaultdict(list)
    for l in linhas:
        por_tipo[l.tipo].append(l)
    def soma(tipo: str) -> int:
        return sum(l.valor_cents for l in por_tipo[tipo])

    pagamentos, saldo, encargos, estornos = soma("pagamento"), soma("saldo_anterior"), soma("encargo"), soma("estorno")
    gastos = [l for l in linhas if l.tipo in ("compra", "encargo")]
    achados: list[tuple[str, str]] = []

    # 1. Linha repetida: o banco cobrou uma vez, o arquivo trouxe duas.
    if mais:
        for (data, titulo, valor), n in Counter((l.data, l.titulo, l.valor_cents) for l in gastos).items():
            if n >= 2 and _igual(valor * (n - 1), a):
                achados.append(("linha_repetida", f"O lançamento \"{titulo}\" de {_brl(valor)} em {_dm(data)} aparece {n} vezes no arquivo. "
                                f"Se o banco cobrou só uma vez, a linha repetida explica a diferença de {_brl(a)}."))

    # 2. O total do banco já descontou o pagamento da fatura anterior (o app deixa o pagamento fora da conta).
    if mais and pagamentos and _igual(pagamentos, a):
        achados.append(("pagamento_ja_descontado", f"A diferença é igual ao pagamento recebido ({_brl(pagamentos)}). "
                        "O total do banco parece já ter descontado o pagamento da fatura anterior."))
    elif mais:
        unico = [l for l in por_tipo["pagamento"] if _igual(l.valor_cents, a)]
        if unico:
            achados.append(("pagamento_ja_descontado", f"A diferença é igual ao pagamento de {_brl(a)} em {_dm(unico[0].data)}. "
                            "O total do banco parece já ter descontado esse pagamento."))

    # 3. O total não inclui o saldo da fatura anterior.
    if mais and saldo and _igual(saldo, a):
        achados.append(("saldo_anterior", f"A diferença é igual ao saldo da fatura anterior ({_brl(saldo)}), que o app somou. "
                        "O total do banco parece não incluí-lo."))

    # 4. O total não inclui juros e taxas.
    if mais and encargos and _igual(encargos, a):
        achados.append(("encargos_fora_do_total", f"A diferença é igual aos juros e taxas ({_brl(encargos)}). "
                        "O total do banco parece não incluir esses encargos."))
    elif mais:
        so_um = [l for l in por_tipo["encargo"] if _igual(l.valor_cents, a)]
        if so_um:
            achados.append(("encargos_fora_do_total", f"A diferença é igual a \"{so_um[0].titulo}\" ({_brl(a)}, {_dm(so_um[0].data)}). "
                            "O total do banco parece não incluir essa cobrança."))

    # 5. O total não desconta os estornos (o app desconta).
    if not mais and estornos and _igual(estornos, a):
        achados.append(("estornos", f"A diferença é igual aos estornos e créditos ({_brl(estornos)}). "
                        "O total do banco parece não tê-los descontado."))

    # 6. Sinal trocado: um estorno que era compra (ou o contrário) muda a conta em 2x o valor dele.
    if not mais:
        suspeitos = [l for l in por_tipo["estorno"] if _igual(2 * l.valor_cents, a)]
        if suspeitos:
            achados.append(("sinal_trocado", f"A diferença é o dobro de {_brl(suspeitos[0].valor_cents)}. O lançamento "
                            f"\"{suspeitos[0].titulo}\" ({_dm(suspeitos[0].data)}) foi lido como estorno e talvez seja uma compra."))
    else:
        suspeitos = [l for l in por_tipo["compra"] if _igual(2 * l.valor_cents, a)]
        if suspeitos:
            achados.append(("sinal_trocado", f"A diferença é o dobro de {_brl(suspeitos[0].valor_cents)}. O lançamento "
                            f"\"{suspeitos[0].titulo}\" ({_dm(suspeitos[0].data)}) foi lido como compra e talvez seja um estorno ou crédito."))

    # 7. O banco fechou a fatura num dia diferente: os lançamentos de uma ponta do período somam a diferença.
    if mais:
        liquido: dict[str, int] = defaultdict(int)
        quantos: Counter[str] = Counter()
        for l in linhas:
            if l.tipo in ("compra", "encargo"):
                liquido[l.data] += l.valor_cents
                quantos[l.data] += 1
            elif l.tipo == "estorno":
                liquido[l.data] -= l.valor_cents
                quantos[l.data] += 1
        datas = sorted(liquido)
        for data in dict.fromkeys(datas[:2] + datas[-2:]):
            # Com um lançamento só no dia, "uma compra" (regra 8) já diz tudo e é mais específica.
            if quantos[data] >= 2 and _igual(liquido[data], a):
                achados.append(("dia_fora_do_periodo", f"Os lançamentos de {_dm(data)} somam {_brl(a)}, a mesma diferença. "
                                "Se o banco fechou a fatura antes ou depois desse dia, o total dele não os inclui."))
                break

    # 8. Uma única compra com o valor da diferença: talvez seja de outra fatura.
    if mais:
        iguais = [l for l in gastos if _igual(l.valor_cents, a)]
        if iguais:
            achados.append(("uma_compra", f"Existe uma compra de {_brl(a)}: {_lista(iguais)}. "
                            "Ela pode ser de outra fatura, ou o banco a contou em outro lugar."))

    # 9. Total digitado com a vírgula no lugar errado.
    if total_cents > 0 and soma_cents > 0:
        for fator in (10, 100):
            if _igual(total_cents * fator, soma_cents):
                achados.append(("virgula", f"O total informado ({_brl(total_cents)}) é {fator} vezes menor que a soma dos lançamentos "
                                f"({_brl(soma_cents)}). Confira a vírgula."))
            if _igual(total_cents, soma_cents * fator):
                achados.append(("virgula", f"O total informado ({_brl(total_cents)}) é {fator} vezes maior que a soma dos lançamentos "
                                f"({_brl(soma_cents)}). Confira a vírgula."))

    # 10. Centavos: arredondamento do banco.
    if a < 100:
        achados.append(("centavos", f"A diferença é só de {_brl(a)}. Costuma ser arredondamento do banco, por exemplo em IOF ou compra "
                        "em moeda estrangeira."))

    # Sem nenhuma pista exata, ao menos diz para que lado a conta erra e onde procurar.
    if not achados:
        if mais:
            achados.append(("sobrando", f"A soma passa do total em {_brl(a)}. Confira se o arquivo tem lançamentos de outra fatura ou "
                            "repetidos, e se o total que você informou é o da fatura certa."))
        else:
            achados.append(("faltando", f"O total do banco é {_brl(a)} maior que a soma dos lançamentos. Pode faltar no arquivo IOF, "
                            "juros, anuidade ou uma compra de cartão adicional. Compare com a fatura no app do banco."))

    vistos: set[str] = set()
    saida: list[dict[str, str]] = []
    for codigo, texto in achados:
        if codigo in vistos:
            continue
        vistos.add(codigo)
        saida.append({"codigo": codigo, "texto": texto})
    return saida[:limite]
