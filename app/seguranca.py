"""Senhas, sessões e freios contra abuso. Só biblioteca padrão."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque

from . import config

_R, _P = 8, 1
_LOG_N_MAX = 20  # teto ao ler um hash gravado: um valor absurdo não pode esgotar a memória
_vaga = threading.BoundedSemaphore(3)  # cada hash usa ~128 MiB com os parâmetros padrão: limita quantos rodam juntos
_dummy: str | None = None

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")
_COMUNS = {
    "1234567890", "12345678910", "0123456789", "senha12345", "password123", "qwertyuiop", "1q2w3e4r5t", "abcdefghij",
    "mudar12345", "brasil2026", "123456789a", "senha123456", "passw0rd123",
}


def _derivar(senha: str, sal: bytes, log_n: int) -> bytes:
    n = 1 << log_n
    with _vaga:
        return hashlib.scrypt(senha.encode(), salt=sal, n=n, r=_R, p=_P, maxmem=2 * 128 * n * _R + (1 << 20), dklen=32)


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    log_n = config.SCRYPT_LOG_N
    return f"scrypt${log_n}${_R}${_P}${sal.hex()}${_derivar(senha, sal, log_n).hex()}"


def conferir_senha(senha: str, gravado: str) -> bool:
    try:
        alg, log_n, r, p, sal, esperado = gravado.split("$")
        log_n = int(log_n)
        if alg != "scrypt" or int(r) != _R or int(p) != _P or not 4 <= log_n <= _LOG_N_MAX:
            return False
        calculado = _derivar(senha, bytes.fromhex(sal), log_n)
        return hmac.compare_digest(calculado, bytes.fromhex(esperado))
    except (ValueError, TypeError):
        return False


def gastar_tempo_de_senha(senha: str) -> None:
    """Quando o e-mail não existe, faz o mesmo trabalho de uma conferência real. Sem isso, o tempo da resposta
    revelaria quais e-mails têm conta."""
    global _dummy
    if _dummy is None:
        _dummy = hash_senha("x" * 12)
    conferir_senha(senha, _dummy)


def validar_email(email: str) -> str | None:
    e = (email or "").strip().lower()
    return e if len(e) <= 254 and EMAIL_RE.match(e) else None


def problema_na_senha(senha: str, email: str = "") -> str | None:
    if len(senha) < 10:
        return "A senha precisa ter pelo menos 10 caracteres."
    if len(senha) > 128:
        return "A senha pode ter no máximo 128 caracteres."
    if senha.lower() in _COMUNS or len(set(senha)) < 4:
        return "Essa senha é fácil de adivinhar. Misture palavras, números e símbolos."
    if email and senha.lower() == email.lower():
        return "A senha não pode ser igual ao e-mail."
    return None


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def novo_codigo() -> str:
    """Código de 6 dígitos para o e-mail de confirmação (aleatório criptográfico; 5 tentativas por código limitam o chute)."""
    return f"{secrets.randbelow(10**6):06d}"


def hash_codigo(codigo: str, sal: str) -> str:
    """O banco guarda só o HMAC do código: ler o arquivo não revela o código ainda válido."""
    return hmac.new(bytes.fromhex(sal), codigo.encode(), hashlib.sha256).hexdigest()


def codigo_confere(codigo: str, sal: str, gravado: str) -> bool:
    return hmac.compare_digest(hash_codigo(codigo.strip(), sal), gravado)


def digest_token(token: str) -> str:
    """O banco guarda só o hash do token da sessão: quem lê o arquivo do banco não consegue entrar com ele."""
    return hashlib.sha256(token.encode()).hexdigest()


class Limite:
    """Janela deslizante em memória: no máximo `maximo` eventos por `janela` segundos para cada chave.

    A memória é limitada a `max_chaves`. Quando enche, sai primeiro o que já expirou, depois quem ainda não chegou ao
    limite (do mais antigo ao mais novo) e só por último quem já está bloqueado. Assim, quem manda milhares de chaves
    diferentes para encher a tabela não consegue apagar o contador de uma chave que está sendo bloqueada."""

    def __init__(self, maximo: int, janela: float, max_chaves: int = 5000):
        self.maximo, self.janela, self.max_chaves = maximo, janela, max_chaves
        self._eventos: dict[str, deque[float]] = {}
        self._trava = threading.Lock()

    def _fila(self, chave: str, agora: float) -> deque[float] | None:
        """Fila da chave já sem eventos vencidos, ou None. Só consulta: nunca cria entrada."""
        q = self._eventos.get(chave)
        if q is None:
            return None
        while q and agora - q[0] > self.janela:
            q.popleft()
        if not q:
            del self._eventos[chave]
            return None
        return q

    def espera(self, chave: str) -> int:
        """Segundos até poder tentar de novo; 0 se já pode."""
        with self._trava:
            agora = time.monotonic()
            q = self._fila(chave, agora)
            return 0 if q is None or len(q) < self.maximo else max(1, int(self.janela - (agora - q[0])) + 1)

    def _abrir_espaco(self, agora: float) -> None:
        alvo = int(self.max_chaves * 0.9)  # abre folga de uma vez, para não repetir a varredura a cada registro
        for passo in range(3):
            for k in list(self._eventos):  # a ordem do dicionário é a de chegada: do mais antigo ao mais novo
                if len(self._eventos) <= alvo:
                    return
                q = self._eventos[k]
                while q and agora - q[0] > self.janela:
                    q.popleft()
                if (passo == 0 and not q) or (passo == 1 and len(q) < self.maximo) or passo == 2:
                    del self._eventos[k]

    def registrar(self, chave: str) -> None:
        with self._trava:
            agora = time.monotonic()
            q = self._fila(chave, agora)
            if q is None:
                if len(self._eventos) >= self.max_chaves:
                    self._abrir_espaco(agora)
                q = self._eventos[chave] = deque()
            q.append(agora)

    def limpar(self) -> None:
        with self._trava:
            self._eventos.clear()

    def zerar(self, chave: str) -> None:
        with self._trava:
            self._eventos.pop(chave, None)
