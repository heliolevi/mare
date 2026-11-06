"""Categorização por regras. Prioridade: regra do usuário > palavras-chave > categoria do arquivo > Outros."""
from __future__ import annotations

import re

from .norm import norm_text

# Categorias que a pessoa escolhe nos lançamentos.
CATEGORIAS_EDITAVEIS = [
    "Alimentação", "Mercado", "Transporte", "Saúde", "Educação", "Lazer",
    "Assinaturas", "Compras", "Casa", "Viagem", "Contas e serviços", "Outros",
]
# Categorias que o app define sozinho pelo tipo do lançamento (não aparecem na troca).
CATEGORIAS_FIXAS = ["Juros e taxas", "Pagamento de fatura", "Entradas", "Investimentos"]
CATEGORIAS = CATEGORIAS_EDITAVEIS + CATEGORIAS_FIXAS

# Ordem importa: o primeiro grupo que casar vence ("uber eats" antes de "uber").
_REGRAS: list[tuple[str, list[str]]] = [
    ("Assinaturas", ["netflix", "spotify", "amazon prime", "prime video", "disney", "hbo", "youtube", "google one",
                     "google storage", "icloud", "apple com bill", "microsoft", "adobe", "chatgpt", "openai",
                     "anthropic", "claude ai", "github", "notion", "canva", "deezer", "globoplay", "paramount"]),
    ("Alimentação", ["uber eats", "ifood", "rappi", "restaurante", "lanchonete", "padaria", "pizzaria", "burger",
                     "mcdonald", "subway", "outback", "cafe", "cafeteria", "sorveteria", "acai", "churrascaria",
                     "bar e", "pastelaria", "confeitaria"]),
    ("Compras", ["mercado livre", "mercadolivre", "amazon", "shopee", "aliexpress", "shein", "magalu",
                 "magazine luiza", "americanas", "casas bahia", "renner", "riachuelo", "c&a", "zara", "kabum"]),
    ("Mercado", ["supermercado", "mercado", "atacadao", "assai", "carrefour", "pao de acucar", "atacarejo",
                 "hortifruti", "mateus", "extra"]),
    ("Transporte", ["uber", "99", "99app", "cabify", "posto", "shell", "ipiranga", "combustivel",
                    "estacionamento", "pedagio", "sem parar", "conectcar"]),
    ("Saúde", ["farmacia", "drogaria", "drogasil", "raia", "pacheco", "pague menos", "hospital", "clinica",
               "laboratorio", "unimed", "odonto"]),
    ("Educação", ["faculdade", "universidade", "curso", "udemy", "alura", "escola", "livraria", "coursera"]),
    ("Lazer", ["cinema", "ingresso", "steam", "playstation", "xbox", "nintendo", "epic games", "academia",
               "smartfit", "gympass", "jiu"]),
    ("Viagem", ["latam", "azul linhas", "gol linhas", "booking", "airbnb", "hotel", "decolar", "hospedagem"]),
    ("Casa", ["leroy", "telhanorte", "tok stok", "madeireira", "ferragens", "eletrica"]),
    ("Contas e serviços", ["claro", "vivo", "tim", "oi fibra", "energia", "equatorial", "agua", "internet",
                           "condominio", "seguro"]),
]
_COMPILADAS = [(cat, re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")\b")) for cat, kws in _REGRAS]

# Categorias que bancos costumam colocar no CSV, traduzidas para as nossas.
_DO_ARQUIVO = {
    "restaurante": "Alimentação", "alimentacao": "Alimentação", "supermercado": "Mercado", "mercado": "Mercado",
    "transporte": "Transporte", "saude": "Saúde", "educacao": "Educação", "lazer": "Lazer",
    "entretenimento": "Lazer", "vestuario": "Compras", "compras": "Compras", "casa": "Casa",
    "viagem": "Viagem", "turismo": "Viagem", "servicos": "Contas e serviços", "assinaturas": "Assinaturas",
}


# Palavras que abrem a descrição de transferências e débitos sem dizer QUEM recebeu ou pagou. Se a chave usasse só as duas
# primeiras palavras, todo "Pix enviado fulano" viraria o mesmo estabelecimento e uma troca de categoria mudaria todos.
_GENERICAS = frozenset(
    "pix transferencia transf ted doc enviado enviada recebido recebida pagamento pgto pagto compra debito credito "
    "boleto saque de da do para em no na via por pelo pela com ao aplicacao resgate".split())


def chave(descricao: str) -> str:
    """Identifica o estabelecimento: 'UBER *TRIP 123' -> 'uber trip'; 'PIX ENVIADO JOAO SILVA' -> 'pix enviado joao silva'."""
    s = re.sub(r"[^a-z ]", " ", norm_text(descricao))
    palavras = [w for w in s.split() if len(w) > 1]
    i = 0
    while i < len(palavras) and palavras[i] in _GENERICAS:
        i += 1
    k = " ".join(palavras[: i + 2][:6])[:100]
    if not k:  # só números ou alfabeto não latino: usa o próprio texto, para nunca juntar lançamentos sem relação
        k = re.sub(r"\s+", " ", descricao.casefold()).strip()[:40]
    return k


_FATURA = re.compile(r"\bfatura\b")


def categorizar(descricao: str, tipo: str, cat_arquivo: str | None, regras_usuario: dict[str, str]) -> str:
    if tipo == "pagamento":
        return "Pagamento de fatura"
    if tipo == "encargo":
        return "Juros e taxas"
    if tipo == "entrada":
        return "Entradas"
    if tipo == "interno":
        return "Pagamento de fatura" if _FATURA.search(norm_text(descricao)) else "Investimentos"
    k = chave(descricao)
    if k in regras_usuario:
        return regras_usuario[k]
    texto = norm_text(descricao)
    for cat, rx in _COMPILADAS:
        if rx.search(texto):
            return cat
    if cat_arquivo:
        mapeada = _DO_ARQUIVO.get(norm_text(cat_arquivo))
        if mapeada:
            return mapeada
    return "Outros"
