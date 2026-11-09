"""API + servidor do app. Rode com: uvicorn app.main:app --reload"""
from __future__ import annotations

import ipaddress
import logging
import mimetypes
import re
import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Path, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, correio, db, seguranca
from .categorize import CATEGORIAS, CATEGORIAS_EDITAVEIS
from .norm import limpar_texto, parse_date, parse_money_cents
from .pipeline import PipelineError, importar

log = logging.getLogger("mare")
mimetypes.add_type("application/manifest+json", ".webmanifest")
app = FastAPI(title="Maré", docs_url=None, redoc_url=None, openapi_url=None)
if config.CONFIRMAR_EMAIL:
    correio.exigir_configuracao()  # falha já na subida se faltar SMTP_HOST etc.

MAX_ID = 2**63 - 1  # o SQLite guarda inteiros de 64 bits; acima disso a consulta estoura
IdDb = Annotated[int, Path(ge=1, le=MAX_ID)]
IdQuery = Annotated[int | None, Query(ge=1, le=MAX_ID)]


def erro(status: int, codigo: str, mensagem: str) -> HTTPException:
    return HTTPException(status, detail={"codigo": codigo, "mensagem": mensagem})


def _json_erro(status: int, codigo: str, mensagem: str) -> JSONResponse:
    return JSONResponse({"detail": {"codigo": codigo, "mensagem": mensagem}}, status_code=status)


# ---------- tratamento de erros: a API sempre responde {"detail": {"codigo", "mensagem"}} ----------
@app.exception_handler(RequestValidationError)
async def _requisicao_invalida(request: Request, exc: RequestValidationError):
    return _json_erro(422, "requisicao_invalida", "Os dados enviados não são válidos. Recarregue a página e tente de novo.")


@app.exception_handler(StarletteHTTPException)
async def _http(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    if request.url.path.startswith("/api/"):
        textos = {404: ("nao_encontrada", "Recurso não encontrado."), 405: ("metodo_invalido", "Operação não permitida.")}
        codigo, msg = textos.get(exc.status_code, ("erro", "Não foi possível concluir a operação."))
        return _json_erro(exc.status_code, codigo, msg)
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def _inesperado(request: Request, exc: Exception):
    log.exception("erro inesperado em %s %s", request.method, request.url.path)
    return _json_erro(500, "erro_interno", "Algo deu errado no servidor. Tente de novo.")


# ---------- contas e sessão: cookie HttpOnly (o JavaScript do app nunca enxerga o token) ----------
COOKIE = "mare_sessao"
# Cookie do cadastro em andamento: prende a confirmação ao navegador que preencheu o formulário. Quem só sabe o e-mail de
# outra pessoa não consegue concluir (nem sequestrar) o cadastro dela, mesmo que o código chegue à caixa certa.
COOKIE_CAD = "mare_cadastro"
CAMINHO_CAD = "/api/auth"
MAX_TENTATIVAS_CODIGO = 5
MAX_ENVIOS_POR_CADASTRO = 5
_lim = {
    "login_ip": seguranca.Limite(10, 60), "login_email": seguranca.Limite(8, 600),
    "cadastro": seguranca.Limite(10, 600), "upload": seguranca.Limite(10, 60),
    "envio_ip": seguranca.Limite(10, 3600), "envio_email": seguranca.Limite(5, 3600), "codigo_ip": seguranca.Limite(15, 600),
}


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _espere(segundos: int, texto: str) -> HTTPException:
    e = erro(429, "muitas_tentativas", f"{texto} Espere {segundos} s e tente de novo.")
    e.headers = {"Retry-After": str(segundos)}
    return e


def usuario_logado(request: Request) -> dict:
    u = db.usuario_da_sessao(request.cookies.get(COOKIE, ""), config.SESSAO_DIAS)
    if not u:
        raise erro(401, "nao_autenticado", "Entre na sua conta para continuar.")
    return u


Usuario = Annotated[dict, Depends(usuario_logado)]


def _abrir_sessao(request: Request, resposta: Response, uid: int) -> None:
    token = seguranca.novo_token()  # sempre um token novo a cada login (evita fixação de sessão)
    db.criar_sessao(uid, token, config.SESSAO_DIAS)
    resposta.set_cookie(COOKIE, token, max_age=config.SESSAO_DIAS * 86400, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")


def _publico(u: dict) -> dict:
    return {"nome": u["nome"], "email": u["email"], "email_confirmado": bool(u["email_confirmado"])}


class Cadastro(BaseModel):
    nome: str = Field(max_length=100)
    email: str = Field(max_length=254)
    senha: str = Field(max_length=200)


class Credenciais(BaseModel):
    email: str = Field(max_length=254)
    senha: str = Field(max_length=200)


@app.get("/api/auth/eu")
def auth_eu(request: Request):
    """Responde 200 mesmo sem sessão: assim a tela de entrada não gera erro vermelho no console do navegador."""
    u = db.usuario_da_sessao(request.cookies.get(COOKIE, ""), config.SESSAO_DIAS)
    return {"usuario": _publico(u) if u else None, "cadastro_aberto": config.CADASTRO_ABERTO or db.total_usuarios() == 0,
            "confirmar_email": config.CONFIRMAR_EMAIL}


@app.post("/api/auth/cadastro", status_code=201)
def auth_cadastro(corpo: Cadastro, request: Request, resposta: Response):
    ip = _ip(request)
    if (w := _lim["cadastro"].espera(ip)):
        raise _espere(w, "Muitas tentativas de cadastro.")
    _lim["cadastro"].registrar(ip)
    if not config.CADASTRO_ABERTO and db.total_usuarios() > 0:
        raise erro(403, "cadastro_fechado", "O cadastro de novas contas está fechado neste servidor.")
    email = seguranca.validar_email(corpo.email)
    nome = limpar_texto(corpo.nome, 60)
    if not nome:
        raise erro(422, "nome_invalido", "Digite seu nome.")
    if not email:
        raise erro(422, "email_invalido", "Esse e-mail não parece válido. Confira e tente de novo.")
    if (problema := seguranca.problema_na_senha(corpo.senha, email)):
        raise erro(422, "senha_fraca", problema)
    if config.CONFIRMAR_EMAIL:
        return _cadastro_com_confirmacao(email, nome, corpo.senha, request, resposta)
    try:
        uid = db.criar_usuario(email, nome, seguranca.hash_senha(corpo.senha))
    except db.EmailEmUso:
        raise erro(409, "email_em_uso", "Já existe uma conta com esse e-mail. Entre nela ou use outro e-mail.")
    _abrir_sessao(request, resposta, uid)
    return {"usuario": _publico({"nome": nome, "email": email, "email_confirmado": 0})}


# ---------- confirmação de e-mail: a conta só nasce depois que o código enviado por SMTP é digitado ----------
class Codigo(BaseModel):
    codigo: str = Field(max_length=20)


def _espere_reenvio(segundos: int) -> HTTPException:
    e = erro(429, "reenvio_cedo", f"Já enviamos um código. Espere {segundos} s para pedir outro.")
    e.headers = {"Retry-After": str(segundos)}
    return e


def _guardar_cookie_cadastro(request: Request, resposta: Response, token: str) -> None:
    resposta.set_cookie(COOKIE_CAD, token, max_age=config.CODIGO_MINUTOS * 60, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path=CAMINHO_CAD)


def _falha_no_envio() -> HTTPException:
    return erro(503, "email_indisponivel", "Não consegui enviar o e-mail agora. Tente de novo em alguns minutos.")


def _checar_limites_de_envio(request: Request, email: str) -> None:
    ip = _ip(request)
    if (w := max(_lim["envio_ip"].espera(ip), _lim["envio_email"].espera(email))):
        raise _espere(w, "Muitos códigos pedidos.")
    _lim["envio_ip"].registrar(ip)
    _lim["envio_email"].registrar(email)


def _cadastro_com_confirmacao(email: str, nome: str, senha: str, request: Request, resposta: Response):
    _checar_limites_de_envio(request, email)
    token = seguranca.novo_token()
    if db.usuario_por_email(email):
        # Mesma resposta de um cadastro novo: quem tenta não descobre que o e-mail já tem conta. A pessoa dona do e-mail
        # recebe um aviso em vez do código.
        seguranca.gastar_tempo_de_senha(senha)
        try:
            correio.enviar_aviso_conta_existente(email)
        except correio.ErroEnvio:
            raise _falha_no_envio()
    else:
        codigo, sal = seguranca.novo_codigo(), secrets.token_hex(16)
        senha_hash = seguranca.hash_senha(senha)
        if (espera := db.pendente_guardar(email, nome, senha_hash, token, seguranca.hash_codigo(codigo, sal), sal,
                                          config.CODIGO_MINUTOS, config.REENVIO_SEGUNDOS)):
            raise _espere_reenvio(espera)
        try:
            correio.enviar_codigo(email, nome, codigo, config.CODIGO_MINUTOS)
        except correio.ErroEnvio:
            db.pendente_remover(email)
            raise _falha_no_envio()
    _guardar_cookie_cadastro(request, resposta, token)
    resposta.status_code = 202
    return {"pendente": True, "email": email, "codigo_minutos": config.CODIGO_MINUTOS, "reenvio_segundos": config.REENVIO_SEGUNDOS}


@app.post("/api/auth/confirmar", status_code=201)
def auth_confirmar(corpo: Codigo, request: Request, resposta: Response):
    if not config.CONFIRMAR_EMAIL:
        raise erro(400, "confirmacao_desligada", "A confirmação por e-mail não está ligada neste servidor.")
    ip = _ip(request)
    if (w := _lim["codigo_ip"].espera(ip)):
        raise _espere(w, "Muitos códigos errados.")
    p = db.pendente_por_token(request.cookies.get(COOKIE_CAD, ""))
    codigo = re.sub(r"\s", "", corpo.codigo or "")  # aceita "123 456"
    if not p:
        _lim["codigo_ip"].registrar(ip)
        raise erro(400, "codigo_invalido", "Código incorreto ou vencido. Confira o e-mail ou peça um novo código.")
    n = db.pendente_tentativa(p["email"])  # conta antes de comparar
    if not (n <= MAX_TENTATIVAS_CODIGO and len(codigo) == 6 and codigo.isdigit()
            and seguranca.codigo_confere(codigo, p["sal"], p["codigo"])):
        _lim["codigo_ip"].registrar(ip)
        if n >= MAX_TENTATIVAS_CODIGO:
            db.pendente_remover(p["email"])
            raise erro(429, "codigo_bloqueado", "Você errou o código vezes demais. Preencha o cadastro de novo para receber outro.")
        raise erro(400, "codigo_invalido", f"Código incorreto. Você ainda tem {MAX_TENTATIVAS_CODIGO - n} tentativa(s).")
    if not config.CADASTRO_ABERTO and db.total_usuarios() > 0:  # a regra vale de novo na hora de criar (alguém pode ter entrado no meio)
        db.pendente_remover(p["email"])
        raise erro(403, "cadastro_fechado", "O cadastro de novas contas está fechado neste servidor.")
    if not db.pendente_remover(p["email"]):  # o código vale uma vez só, mesmo com dois pedidos ao mesmo tempo
        raise erro(400, "codigo_invalido", "Código incorreto ou vencido. Confira o e-mail ou peça um novo código.")
    try:
        uid = db.criar_usuario(p["email"], p["nome"], p["senha"], confirmado=True)
    except db.EmailEmUso:
        raise erro(409, "email_em_uso", "Já existe uma conta com esse e-mail. Entre nela.")
    _abrir_sessao(request, resposta, uid)
    resposta.delete_cookie(COOKIE_CAD, path=CAMINHO_CAD, httponly=True, samesite="strict")
    return {"usuario": _publico({"nome": p["nome"], "email": p["email"], "email_confirmado": 1})}


@app.post("/api/auth/reenviar", status_code=202)
def auth_reenviar(request: Request):
    if not config.CONFIRMAR_EMAIL:
        raise erro(400, "confirmacao_desligada", "A confirmação por e-mail não está ligada neste servidor.")
    p = db.pendente_por_token(request.cookies.get(COOKIE_CAD, ""))
    if not p:
        raise erro(400, "cadastro_vencido", "Esse cadastro venceu. Preencha o formulário de novo.")
    _checar_limites_de_envio(request, p["email"])
    codigo, sal = seguranca.novo_codigo(), secrets.token_hex(16)
    r = db.pendente_reenviar(p["email"], seguranca.hash_codigo(codigo, sal), sal, config.CODIGO_MINUTOS, config.REENVIO_SEGUNDOS,
                             MAX_ENVIOS_POR_CADASTRO)
    if r == -2:
        raise erro(400, "cadastro_vencido", "Esse cadastro venceu. Preencha o formulário de novo.")
    if r == -1:
        raise erro(429, "limite_de_envios", "Você já pediu códigos demais para esse cadastro. Preencha o formulário de novo daqui a pouco.")
    if r > 0:
        raise _espere_reenvio(r)
    try:
        correio.enviar_codigo(p["email"], p["nome"], codigo, config.CODIGO_MINUTOS)
    except correio.ErroEnvio:
        raise _falha_no_envio()
    return {"pendente": True, "email": p["email"], "codigo_minutos": config.CODIGO_MINUTOS, "reenvio_segundos": config.REENVIO_SEGUNDOS}


@app.post("/api/auth/entrar")
def auth_entrar(corpo: Credenciais, request: Request, resposta: Response):
    ip, email = _ip(request), (corpo.email or "").strip().lower()
    if (w := max(_lim["login_ip"].espera(ip), _lim["login_email"].espera(email))):
        raise _espere(w, "Muitas tentativas de entrada.")
    u = db.usuario_por_email(email)
    if not (u and seguranca.conferir_senha(corpo.senha, u["senha"])):
        if not u:
            seguranca.gastar_tempo_de_senha(corpo.senha)  # mesmo tempo de resposta com ou sem conta
        _lim["login_ip"].registrar(ip)
        _lim["login_email"].registrar(email)
        raise erro(401, "credenciais_invalidas", "E-mail ou senha incorretos.")
    _lim["login_email"].zerar(email)
    _abrir_sessao(request, resposta, u["id"])
    return {"usuario": _publico(u)}


@app.post("/api/auth/sair", status_code=204)
def auth_sair(request: Request):
    if (token := request.cookies.get(COOKIE)):
        db.encerrar_sessao(token)
    r = Response(status_code=204)
    r.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
    return r


# ---------- proteção da borda: host, origem, tamanho do corpo e cabeçalhos ----------
_CABECALHOS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    ),
}


def _host_ok(host: str) -> bool:
    """Aceita localhost, endereços IP e os nomes de ALLOWED_HOSTS. Um site externo que aponta o próprio domínio para
    127.0.0.1 (DNS rebinding) chega aqui com o domínio dele no Host e é recusado."""
    if not host or "@" in host:
        return False
    nome = (urlsplit("//" + host).hostname or "").lower()
    if not nome:
        return False
    if nome == "localhost" or nome.endswith(".localhost") or nome in config.ALLOWED_HOSTS:
        return True
    try:
        ipaddress.ip_address(nome)
        return True
    except ValueError:
        return False


def _origem_ok(origem: str, host: str) -> bool:
    return urlsplit(origem).netloc.lower() == host.lower()


class _CorpoGrande(BaseException):  # BaseException: o FastAPI engoliria uma Exception e a trocaria por um 400 genérico
    pass


class Guarda:
    """Middleware ASGI puro (não bufferiza o corpo): confere Host e Origin, corta corpos grandes mesmo sem Content-Length
    (envio em pedaços) e põe os cabeçalhos de segurança em toda resposta."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cab = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        caminho, metodo = scope["path"], scope["method"]
        api = caminho.startswith("/api/")
        iniciou = False

        async def enviar(msg):
            nonlocal iniciou
            if msg["type"] == "http.response.start":
                iniciou = True
                h = MutableHeaders(scope=msg)
                for k, v in _CABECALHOS.items():
                    h[k] = v
                if api:
                    h["Cache-Control"] = "no-store"
            await send(msg)

        async def negar(status, codigo, mensagem):
            await _json_erro(status, codigo, mensagem)(scope, receive, enviar)

        host = cab.get("host", "")
        if not _host_ok(host):
            return await negar(400, "host_invalido", "Endereço não permitido. Acesse pelo localhost ou configure ALLOWED_HOSTS.")
        if metodo not in ("GET", "HEAD", "OPTIONS") and "origin" in cab and not _origem_ok(cab["origin"], host):
            return await negar(403, "origem_invalida", "Requisição de outro site recusada.")

        limite = None
        if api and metodo in ("POST", "PUT", "PATCH"):
            limite = int(config.MAX_UPLOAD_MB * 1024 * 1024) + 256 * 1024 if caminho == "/api/faturas" else 4 * 1024 * 1024
            declarado = cab.get("content-length", "")
            if declarado.isdigit() and int(declarado) > limite:
                return await negar(413, "arquivo_grande", f"O arquivo passa de {config.MAX_UPLOAD_MB:g} MB.")
        recebido = 0

        async def receber():
            nonlocal recebido
            msg = await receive()
            if limite is not None and msg["type"] == "http.request":
                recebido += len(msg.get("body", b""))
                if recebido > limite:
                    raise _CorpoGrande()
            return msg

        try:
            await self.app(scope, receber, enviar)
        except _CorpoGrande:
            if not iniciou:
                await negar(413, "arquivo_grande", f"O arquivo passa de {config.MAX_UPLOAD_MB:g} MB.")


app.add_middleware(Guarda)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/categorias")
def categorias(_: Usuario):
    return CATEGORIAS_EDITAVEIS


def _total_ou_erro(texto: str | None) -> int | None:
    if not texto or not texto.strip():
        return None
    c = parse_money_cents(texto)
    if c is None or c <= 0:
        raise erro(422, "total_invalido", "O total da fatura não parece um valor válido. Exemplo: 1.234,56")
    return abs(c)


def _venc_ou_erro(texto: str | None):
    if not texto or not texto.strip():
        return None
    v = parse_date(texto.strip())
    if v is None:
        raise erro(422, "vencimento_invalido", "Use a data de vencimento no formato dd/mm/aaaa.")
    return v


@app.post("/api/faturas", status_code=201)
def enviar(u: Usuario, resposta: Response, arquivo: UploadFile = File(...), total: str | None = Form(None, max_length=40),
           vencimento: str | None = Form(None, max_length=40), cartao: str | None = Form(None, max_length=200)):
    _lim["upload"].maximo = config.UPLOADS_POR_MINUTO
    if (w := _lim["upload"].espera(str(u["id"]))):
        raise _espere(w, "Muitos envios seguidos.")
    _lim["upload"].registrar(str(u["id"]))
    limite = int(config.MAX_UPLOAD_MB * 1024 * 1024)
    dados = arquivo.file.read(limite + 1)
    if len(dados) > limite:
        raise erro(413, "arquivo_grande", f"O arquivo passa de {config.MAX_UPLOAD_MB:g} MB.")
    if not dados:
        raise erro(422, "arquivo_vazio", "O arquivo está vazio.")

    total_c = _total_ou_erro(total)
    venc = _venc_ou_erro(vencimento)
    nome = (cartao or "").strip() or None

    try:
        fatura = importar(dados, arquivo.filename or "", db.regras_usuario(u["id"]), total_cents=total_c,
                          vencimento=venc, nome=nome)
        fid, acrescentados = db.salvar(fatura, u["id"])
    except PipelineError as e:
        raise erro(e.status, e.codigo, e.mensagem)
    except db.Duplicada as e:
        raise erro(409, "ja_importada", f"Esta fatura já foi importada (número {e.fatura_id}).")
    out = db.obter(fid, u["id"])
    if acrescentados is not None:  # arquivo mais completo de uma fatura que já existia: não criou outra
        resposta.status_code = 200
        out["atualizada"] = {"novos": acrescentados}
    return out


@app.get("/api/faturas")
def listar_faturas(u: Usuario):
    return db.listar(u["id"])


@app.get("/api/faturas/{fid}")
def obter_fatura(fid: IdDb, u: Usuario):
    f = db.obter(fid, u["id"])
    if not f:
        raise erro(404, "nao_encontrada", "Fatura não encontrada.")
    return f


class AtualizarFatura(BaseModel):
    total: str | None = Field(None, max_length=40)
    vencimento: str | None = Field(None, max_length=40)


@app.patch("/api/faturas/{fid}")
def atualizar_fatura(fid: IdDb, corpo: AtualizarFatura, u: Usuario):
    atual = db.obter(fid, u["id"])
    if not atual:
        raise erro(404, "nao_encontrada", "Fatura não encontrada.")
    if atual["conta"] and corpo.total and corpo.total.strip():
        raise erro(422, "conta_sem_total", "Extrato de conta não tem total de fatura para conferir.")
    total_c = _total_ou_erro(corpo.total)
    venc = _venc_ou_erro(corpo.vencimento)
    f = db.atualizar_total(fid, u["id"], total_c, venc)
    if not f:
        raise erro(404, "nao_encontrada", "Fatura não encontrada.")
    return f


@app.delete("/api/faturas/{fid}", status_code=204)
def excluir_fatura(fid: IdDb, u: Usuario):
    if not db.excluir(fid, u["id"]):
        raise erro(404, "nao_encontrada", "Fatura não encontrada.")
    return Response(status_code=204)


class TrocarCategoria(BaseModel):
    categoria: str = Field(max_length=60)


@app.patch("/api/transacoes/{tx_id}")
def trocar_categoria(tx_id: IdDb, corpo: TrocarCategoria, u: Usuario):
    if corpo.categoria not in CATEGORIAS_EDITAVEIS:
        raise erro(422, "categoria_invalida", "Categoria desconhecida.")
    try:
        r = db.trocar_categoria(tx_id, u["id"], corpo.categoria)
    except db.TipoFixo:
        raise erro(409, "categoria_fixa", "A categoria deste lançamento é definida pelo app e não pode ser trocada.")
    if not r:
        raise erro(404, "nao_encontrada", "Transação não encontrada.")
    return r


class ItemRestaurar(BaseModel):
    id: int = Field(ge=1, le=MAX_ID)
    categoria: str = Field(max_length=60)


class Restaurar(BaseModel):
    itens: list[ItemRestaurar] = Field(max_length=20000)
    chave: str = Field(min_length=1, max_length=100)
    categoria_regra: str = Field(max_length=60)


@app.post("/api/transacoes/restaurar", status_code=204)
def restaurar(corpo: Restaurar, u: Usuario):
    if corpo.categoria_regra not in CATEGORIAS or any(i.categoria not in CATEGORIAS for i in corpo.itens):
        raise erro(422, "categoria_invalida", "Categoria desconhecida.")
    if not db.restaurar(u["id"], [{"id": i.id, "categoria": i.categoria} for i in corpo.itens], corpo.chave, corpo.categoria_regra):
        raise erro(422, "chave_desconhecida", "Não encontrei esse estabelecimento para desfazer a troca.")
    return Response(status_code=204)


@app.get("/api/resumo")
def resumo(u: Usuario, fatura_id: IdQuery = None):
    r = db.resumo(fatura_id, u["id"])
    if not r:
        raise erro(404, "sem_faturas", "Nenhuma fatura importada ainda.")
    return r


@app.get("/api/parcelas-futuras")
def parcelas_futuras(u: Usuario):
    return db.parcelas_futuras(u["id"])


@app.api_route("/api/{resto:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_inexistente(resto: str):
    # Sem isso, um caminho de API errado cairia na página 404 em HTML dos arquivos estáticos.
    raise erro(404, "nao_encontrada", "Recurso não encontrado.")


app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
