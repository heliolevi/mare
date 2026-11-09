"""Envio de e-mail por SMTP (só biblioteca padrão). Hoje serve para o código de confirmação do cadastro."""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from . import config

log = logging.getLogger("mare")
_LOCAL = {"localhost", "127.0.0.1", "::1"}


class ErroEnvio(Exception):
    """Falha ao entregar o e-mail ao servidor SMTP. A mensagem nunca carrega senha nem o conteúdo enviado."""


def exigir_configuracao() -> None:
    """Chamado na subida do servidor quando CONFIRMAR_EMAIL=1: melhor não subir do que aceitar cadastros que nunca confirmam."""
    falta = [n for n, v in (("SMTP_HOST", config.SMTP_HOST), ("SMTP_REMETENTE (ou SMTP_USUARIO)", config.SMTP_REMETENTE)) if not v]
    if falta:
        raise RuntimeError(f"CONFIRMAR_EMAIL=1 exige {' e '.join(falta)} no .env.")
    if config.SMTP_SEGURANCA not in ("starttls", "ssl", "nenhuma"):
        raise RuntimeError("SMTP_SEGURANCA deve ser starttls, ssl ou nenhuma.")
    if config.SMTP_SEGURANCA == "nenhuma" and config.SMTP_USUARIO and config.SMTP_HOST.lower() not in _LOCAL:
        raise RuntimeError("Com SMTP_SEGURANCA=nenhuma a senha SMTP iria em texto puro: isso só é aceito em localhost.")


def enviar(para: str, assunto: str, texto: str, corpo_html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr(("Maré", config.SMTP_REMETENTE))
    msg["To"] = para
    msg["Subject"] = assunto
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=config.SMTP_REMETENTE.rpartition("@")[2] or None)
    msg.set_content(texto)
    if corpo_html:
        msg.add_alternative(corpo_html, subtype="html")
    try:
        if config.SMTP_SEGURANCA == "ssl":
            s: smtplib.SMTP = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORTA, timeout=15, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORTA, timeout=15)
        with s:
            if config.SMTP_SEGURANCA == "starttls":
                s.starttls(context=ssl.create_default_context())  # valida o certificado: sem isso o código passaria em claro
            if config.SMTP_USUARIO:
                s.login(config.SMTP_USUARIO, config.SMTP_SENHA)
            s.send_message(msg)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
        # só o tipo do erro vai para o log: a mensagem do servidor pode repetir o endereço ou parte do conteúdo
        log.warning("falha ao enviar e-mail por SMTP: %s", type(e).__name__)
        raise ErroEnvio(type(e).__name__) from None


def enviar_codigo(para: str, nome: str, codigo: str, minutos: int) -> None:
    texto = (
        f"Olá, {nome}.\n\n"
        f"Seu código para confirmar o e-mail na Maré é:\n\n    {codigo}\n\n"
        f"Ele vale por {minutos} minutos. Digite no app para criar sua conta.\n\n"
        "Se não foi você, ignore este e-mail: nenhuma conta será criada.\n"
    )
    pagina = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#0b1b33;max-width:32rem">'
        f"<p>Olá, {html.escape(nome)}.</p><p>Seu código para confirmar o e-mail na Maré é:</p>"
        f'<p style="font-size:2rem;letter-spacing:.35em;font-weight:700;margin:1rem 0">{html.escape(codigo)}</p>'
        f"<p>Ele vale por {minutos} minutos. Digite no app para criar sua conta.</p>"
        '<p style="color:#51647e">Se não foi você, ignore este e-mail: nenhuma conta será criada.</p></div>'
    )
    enviar(para, "Seu código de confirmação da Maré", texto, pagina)


def enviar_aviso_conta_existente(para: str) -> None:
    enviar(
        para, "Sua conta na Maré",
        "Alguém tentou criar uma conta na Maré com este e-mail, mas ela já existe.\n\n"
        "Se foi você, é só entrar com o seu e-mail e a sua senha.\n"
        "Se não foi, pode ignorar esta mensagem: nada foi alterado.\n",
    )
