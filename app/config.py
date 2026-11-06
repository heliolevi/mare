"""Configuração via variáveis de ambiente (ou arquivo .env na raiz do projeto)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

# Contas: a senha é guardada com scrypt (N = 2^SCRYPT_LOG_N). 17 é o mínimo recomendado pela OWASP; testes usam menos.
SCRYPT_LOG_N = int(os.getenv("SCRYPT_LOG_N", "17"))
SESSAO_DIAS = int(os.getenv("SESSAO_DIAS", "14"))
# Depois da primeira conta, só cria novas quem estiver com CADASTRO_ABERTO=1. Padrão fechado: app pessoal, dados financeiros.
CADASTRO_ABERTO = os.getenv("CADASTRO_ABERTO", "0").lower() in ("1", "true", "sim")
# Envios de arquivo por usuário por minuto.
UPLOADS_POR_MINUTO = int(os.getenv("UPLOADS_POR_MINUTO", "10"))
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "mare.db"))
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "5"))
STATIC_DIR = ROOT / "static"
# Máximo de lançamentos por arquivo (um cartão real tem algumas centenas; o limite protege a tela e a projeção de parcelas).
MAX_LINHAS = int(os.getenv("MAX_LINHAS", "3000"))
# Nomes de host aceitos além de localhost e endereços IP (separados por vírgula). Bloqueia ataques de DNS rebinding:
# um site externo que aponta o próprio domínio para 127.0.0.1 e tenta falar com o app como se fosse da mesma origem.
ALLOWED_HOSTS = {h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()}
