"""Persistência em SQLite (arquivo local). Valores sempre em centavos inteiros."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from . import config
from .categorize import categorizar, chave
from .models import Fatura, RawTx
from .pipeline import _classificar, escolher_convencao, hash_conteudo, soma_cents, soma_saidas_cents, tipo_conta
from .seguranca import digest_token

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE, nome TEXT NOT NULL, senha TEXT NOT NULL,
  email_confirmado INTEGER NOT NULL DEFAULT 0,
  criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Cadastros que esperam o código do e-mail: a conta só vira linha de `usuarios` quando o código é confirmado.
CREATE TABLE IF NOT EXISTS cadastros_pendentes (
  email TEXT PRIMARY KEY, nome TEXT NOT NULL, senha TEXT NOT NULL,
  token TEXT NOT NULL,      -- sha256 do cookie que prende a confirmação ao navegador que fez o cadastro
  codigo TEXT NOT NULL, sal TEXT NOT NULL,
  tentativas INTEGER NOT NULL DEFAULT 0, envios INTEGER NOT NULL DEFAULT 1,
  enviado_em TEXT NOT NULL DEFAULT (datetime('now')), expira_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes (
  token TEXT PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  expira_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS faturas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
  emissor TEXT, vencimento TEXT, fechamento TEXT, referencia TEXT NOT NULL,
  total_cents INTEGER, soma_cents INTEGER NOT NULL, diff_cents INTEGER,
  status TEXT NOT NULL, formato TEXT NOT NULL, arquivo TEXT,
  hash TEXT NOT NULL UNIQUE, avisos TEXT NOT NULL DEFAULT '[]', conta INTEGER NOT NULL DEFAULT 0, origem TEXT,
  criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transacoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fatura_id INTEGER NOT NULL REFERENCES faturas(id) ON DELETE CASCADE,
  data TEXT NOT NULL, descricao TEXT NOT NULL, chave TEXT NOT NULL,
  valor_cents INTEGER NOT NULL, bruto_cents INTEGER NOT NULL, tipo TEXT NOT NULL,
  parcela_atual INTEGER, parcela_total INTEGER, categoria TEXT NOT NULL, fitid TEXT
);
CREATE TABLE IF NOT EXISTS regras (
  usuario_id INTEGER NOT NULL, chave TEXT NOT NULL, categoria TEXT NOT NULL, PRIMARY KEY (usuario_id, chave)
);
"""

# Índices ficam fora do SCHEMA: em bancos antigos as colunas novas só existem depois da migração.
INDICES = """
CREATE INDEX IF NOT EXISTS ix_tx_fatura ON transacoes(fatura_id);
CREATE INDEX IF NOT EXISTS ix_tx_chave ON transacoes(chave);
CREATE INDEX IF NOT EXISTS ix_fat_usuario ON faturas(usuario_id);
CREATE INDEX IF NOT EXISTS ix_sessoes_usuario ON sessoes(usuario_id);
CREATE INDEX IF NOT EXISTS ix_pendentes_token ON cadastros_pendentes(token);
"""

ORIGEM = "COALESCE(NULLIF(emissor,''), origem, '')"  # separa cartões: pelo nome, ou pela assinatura do arquivo
GASTO = "SUM(CASE tipo WHEN 'compra' THEN valor_cents WHEN 'encargo' THEN valor_cents WHEN 'estorno' THEN -valor_cents ELSE 0 END)"


class TipoFixo(Exception):
    """Lançamento cuja categoria o app define sozinho (juros, pagamento de fatura, entradas...)."""


class Duplicada(Exception):
    def __init__(self, fatura_id: int):
        super().__init__("fatura já importada")
        self.fatura_id = fatura_id


class EmailEmUso(Exception):
    pass


_VERSAO_SCHEMA = 3
_prontos: set[str] = set()
_trava = threading.Lock()


def _colunas(c: sqlite3.Connection, tabela: str) -> set[str]:
    return {r["name"] for r in c.execute(f"PRAGMA table_info({tabela})")}


def _preparar(c: sqlite3.Connection) -> None:
    """Cria as tabelas e migra bancos antigos. Roda uma vez por arquivo de banco, não a cada requisição."""
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    versao = c.execute("PRAGMA user_version").fetchone()[0]
    if versao < _VERSAO_SCHEMA:
        _migrar(c, versao)
    c.executescript(INDICES)
    c.execute(f"PRAGMA user_version={_VERSAO_SCHEMA}")
    c.commit()


def _migrar(c: sqlite3.Connection, versao: int) -> None:
    cols = _colunas(c, "faturas")
    for nome, ddl in (("conta", "INTEGER NOT NULL DEFAULT 0"),
                      ("usuario_id", "INTEGER REFERENCES usuarios(id) ON DELETE CASCADE"), ("origem", "TEXT")):
        if nome not in cols:
            c.execute(f"ALTER TABLE faturas ADD COLUMN {nome} {ddl}")
    if versao < 2:
        # 1) a chave do estabelecimento ficou mais específica: recalcula as já gravadas
        for t in c.execute("SELECT id, descricao FROM transacoes").fetchall():
            c.execute("UPDATE transacoes SET chave=? WHERE id=?", (chave(t["descricao"]), t["id"]))
        # 2) extratos de conta importados antes como se fossem cartão: reclassifica entradas e saídas
        _corrigir_contas_antigas(c)
        _recalcular_hashes(c)
    if "usuario_id" not in _colunas(c, "regras"):
        # versão 3: regras de categoria passam a ser de cada usuário. As antigas ficam com usuario_id 0 até a primeira conta adotá-las.
        c.execute("ALTER TABLE regras RENAME TO regras_antiga")
        c.execute("CREATE TABLE regras (usuario_id INTEGER NOT NULL, chave TEXT NOT NULL, categoria TEXT NOT NULL, "
                  "PRIMARY KEY (usuario_id, chave))")
        c.execute("INSERT INTO regras SELECT 0, chave, categoria FROM regras_antiga")
        c.execute("DROP TABLE regras_antiga")


def _corrigir_contas_antigas(c: sqlite3.Connection) -> None:
    for f in c.execute("SELECT id, avisos FROM faturas WHERE conta=0 AND avisos LIKE '%conta corrente%'").fetchall():
        avisos = [a for a in json.loads(f["avisos"] or "[]") if "conta corrente" not in a and not a.startswith("Interpretei")
                  and not a.startswith("Inverti")]
        avisos.append("Extrato de conta: só as saídas contam como gasto. Entradas, pagamento de fatura e aplicações ficam fora da conta.")
        regras = {x["chave"]: x["categoria"] for x in c.execute("SELECT chave, categoria FROM regras")}
        rows = c.execute("SELECT * FROM transacoes WHERE fatura_id=?", (f["id"],)).fetchall()
        raws = [RawTx(data=date.fromisoformat(r["data"]), descricao=r["descricao"], bruto_cents=r["bruto_cents"]) for r in rows]
        pares = [(raw, tipo_conta(raw)) for raw in raws]
        for r, (_, tipo) in zip(rows, pares):
            if tipo != r["tipo"]:
                c.execute("UPDATE transacoes SET tipo=?, valor_cents=?, categoria=? WHERE id=?",
                          (tipo, abs(r["bruto_cents"]), categorizar(r["descricao"], tipo, None, regras), r["id"]))
        c.execute("""UPDATE faturas SET conta=1, total_cents=NULL, diff_cents=NULL, status='sem_total', soma_cents=?, avisos=?
                     WHERE id=?""", (soma_saidas_cents(pares), json.dumps(avisos, ensure_ascii=False), f["id"]))


def _recalcular_hashes(c: sqlite3.Connection) -> None:
    """Hash novo = só o conteúdo (ver hash_conteudo). Se duas faturas já importadas colidirem, a mais nova mantém o hash antigo."""
    for f in c.execute("SELECT id, formato FROM faturas ORDER BY id").fetchall():
        itens = [(t["data"], t["descricao"], t["bruto_cents"], t["fitid"] or "") for t in c.execute(
            "SELECT data, descricao, bruto_cents, fitid FROM transacoes WHERE fatura_id=?", (f["id"],))]
        try:
            c.execute("UPDATE faturas SET hash=? WHERE id=?", (hash_conteudo(f["formato"], itens), f["id"]))
        except sqlite3.IntegrityError:
            pass


@contextmanager
def conn():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        if config.DB_PATH not in _prontos:
            with _trava:
                if config.DB_PATH not in _prontos:
                    _preparar(c)
                    _prontos.add(config.DB_PATH)
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# ---------------------------------------------------------------- contas e sessões
def _hash_do_usuario(uid: int, h: str) -> str:
    """O mesmo arquivo pode ser importado por usuários diferentes: o hash de duplicidade inclui o dono."""
    return hashlib.sha256(f"{uid}:{h}".encode()).hexdigest()


def total_usuarios() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]


def criar_usuario(email: str, nome: str, senha_hash: str, confirmado: bool = False) -> int:
    with conn() as c:
        try:
            cur = c.execute("INSERT INTO usuarios (email, nome, senha, email_confirmado) VALUES (?,?,?,?)",
                            (email, nome, senha_hash, int(confirmado)))
        except sqlite3.IntegrityError:
            raise EmailEmUso() from None
        uid = cur.lastrowid
        if c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1:
            # Primeira conta do banco: adota os dados que já existiam antes de haver contas.
            for f in c.execute("SELECT id, hash FROM faturas WHERE usuario_id IS NULL").fetchall():
                c.execute("UPDATE faturas SET usuario_id=?, hash=? WHERE id=?", (uid, _hash_do_usuario(uid, f["hash"]), f["id"]))
            c.execute("UPDATE regras SET usuario_id=? WHERE usuario_id=0", (uid,))
        return uid


def usuario_por_email(email: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
        return dict(r) if r else None


# ---------------------------------------------------------------- cadastros pendentes (confirmação por e-mail)
def _segundos_desde(c: sqlite3.Connection, coluna: str, tabela_where: str, params: tuple) -> int:
    return int(c.execute(f"SELECT CAST(strftime('%s','now') - strftime('%s', {coluna}) AS INTEGER) FROM {tabela_where}", params).fetchone()[0])


def pendente_guardar(email: str, nome: str, senha_hash: str, token: str, codigo_hash: str, sal: str,
                     validade_min: int, reenvio_s: int) -> int:
    """Grava (ou troca) o cadastro pendente do e-mail. Devolve 0 se gravou; se já havia um enviado há menos de `reenvio_s`
    segundos, não mexe em nada e devolve quantos segundos faltam (quem chega no meio da janela não consegue trocar a senha
    de um cadastro que outra pessoa acabou de abrir)."""
    with conn() as c:
        c.execute("DELETE FROM cadastros_pendentes WHERE expira_em < datetime('now')")
        antigo = c.execute("SELECT envios FROM cadastros_pendentes WHERE email=?", (email,)).fetchone()
        if antigo:
            passou = _segundos_desde(c, "enviado_em", "cadastros_pendentes WHERE email=?", (email,))
            if passou < reenvio_s:
                return reenvio_s - passou
        c.execute("""INSERT OR REPLACE INTO cadastros_pendentes (email, nome, senha, token, codigo, sal, tentativas, envios, enviado_em, expira_em)
                     VALUES (?,?,?,?,?,?,0,1,datetime('now'),datetime('now', ?))""",
                  (email, nome, senha_hash, digest_token(token), codigo_hash, sal, f"+{int(validade_min)} minutes"))
        return 0


def pendente_por_token(token: str) -> dict | None:
    if not token or len(token) > 200:
        return None
    with conn() as c:
        c.execute("DELETE FROM cadastros_pendentes WHERE expira_em < datetime('now')")
        r = c.execute("SELECT * FROM cadastros_pendentes WHERE token=?", (digest_token(token),)).fetchone()
        return dict(r) if r else None


def pendente_tentativa(email: str) -> int:
    """Conta uma tentativa de código (antes de comparar, para pedidos simultâneos não ganharem chutes extras)."""
    with conn() as c:
        c.execute("UPDATE cadastros_pendentes SET tentativas=tentativas+1 WHERE email=?", (email,))
        r = c.execute("SELECT tentativas FROM cadastros_pendentes WHERE email=?", (email,)).fetchone()
        return r[0] if r else 99


def pendente_reenviar(email: str, codigo_hash: str, sal: str, validade_min: int, reenvio_s: int, max_envios: int) -> int:
    """Novo código para o mesmo cadastro. 0 = trocado; >0 = segundos de espera; -1 = limite de envios do cadastro."""
    with conn() as c:
        r = c.execute("SELECT envios FROM cadastros_pendentes WHERE email=?", (email,)).fetchone()
        if not r:
            return -2
        passou = _segundos_desde(c, "enviado_em", "cadastros_pendentes WHERE email=?", (email,))
        if passou < reenvio_s:
            return reenvio_s - passou
        if r["envios"] >= max_envios:
            return -1
        c.execute("""UPDATE cadastros_pendentes SET codigo=?, sal=?, tentativas=0, envios=envios+1, enviado_em=datetime('now'),
                     expira_em=datetime('now', ?) WHERE email=?""", (codigo_hash, sal, f"+{int(validade_min)} minutes", email))
        return 0


def pendente_remover(email: str) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM cadastros_pendentes WHERE email=?", (email,)).rowcount == 1


def criar_sessao(uid: int, token: str, dias: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM sessoes WHERE expira_em < datetime('now')")
        c.execute("INSERT INTO sessoes (token, usuario_id, expira_em) VALUES (?,?,datetime('now', ?))",
                  (digest_token(token), uid, f"+{int(dias)} days"))
        # no máximo 10 sessões por conta: a mais antiga cai
        c.execute("""DELETE FROM sessoes WHERE usuario_id=? AND token NOT IN
                     (SELECT token FROM sessoes WHERE usuario_id=? ORDER BY expira_em DESC LIMIT 10)""", (uid, uid))


def usuario_da_sessao(token: str, dias: int) -> dict | None:
    if not token or len(token) > 200:
        return None
    with conn() as c:
        r = c.execute("""SELECT u.id, u.nome, u.email, u.email_confirmado FROM sessoes s JOIN usuarios u ON u.id=s.usuario_id
                         WHERE s.token=? AND s.expira_em > datetime('now')""", (digest_token(token),)).fetchone()
        if not r:
            return None
        # sessão deslizante: quem usa o app não é deslogado, quem some por 14 dias é
        c.execute("UPDATE sessoes SET expira_em=datetime('now', ?) WHERE token=? AND expira_em < datetime('now', ?)",
                  (f"+{int(dias)} days", digest_token(token), f"+{int(dias) - 1} days"))
        return dict(r)


def encerrar_sessao(token: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM sessoes WHERE token=?", (digest_token(token),))


# ---------------------------------------------------------------- faturas (sempre do usuário dono)
def regras_usuario(uid: int) -> dict[str, str]:
    with conn() as c:
        return {r["chave"]: r["categoria"] for r in c.execute("SELECT chave, categoria FROM regras WHERE usuario_id=?", (uid,))}


def _inserir_txs(c: sqlite3.Connection, fid: int, txs: list) -> None:
    c.executemany(
        """INSERT INTO transacoes (fatura_id, data, descricao, chave, valor_cents, bruto_cents, tipo,
           parcela_atual, parcela_total, categoria, fitid) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [(fid, t.data.isoformat(), t.descricao, chave(t.descricao), t.valor_cents, t.bruto_cents, t.tipo,
          t.parcela_atual, t.parcela_total, t.categoria, t.fitid) for t in txs])


def _parecida(c: sqlite3.Connection, f: Fatura, uid: int) -> tuple[int, Counter] | None:
    """Procura uma fatura já importada que seja a mesma, só que exportada em outro dia (com mais ou menos lançamentos).
    Critério: mesmo tipo (cartão/conta), mesmo emissor (ou algum sem nome), perto no calendário e pelo menos 80% dos
    lançamentos do menor arquivo iguais em data, descrição e valor."""
    novas = Counter((t.data.isoformat(), t.descricao, t.bruto_cents) for t in f.txs)
    melhor: tuple[int, int] | None = None
    for r in c.execute(
            """SELECT id, emissor FROM faturas WHERE usuario_id=? AND conta=? AND ABS(julianday(referencia) - julianday(?)) <= 62""",
            (uid, int(f.conta), f.referencia.isoformat())).fetchall():
        if r["emissor"] and f.emissor and r["emissor"].casefold() != f.emissor.casefold():
            continue
        antigas = Counter((t["data"], t["descricao"], t["bruto_cents"]) for t in c.execute(
            "SELECT data, descricao, bruto_cents FROM transacoes WHERE fatura_id=?", (r["id"],)))
        menor = min(sum(antigas.values()), sum(novas.values()))
        casadas = sum((novas & antigas).values())
        if menor and casadas / menor >= 0.8 and (melhor is None or casadas > melhor[1]):
            melhor = (r["id"], casadas)
    if not melhor:
        return None
    antigas = Counter((t["data"], t["descricao"], t["bruto_cents"]) for t in c.execute(
        "SELECT data, descricao, bruto_cents FROM transacoes WHERE fatura_id=?", (melhor[0],)))
    return melhor[0], novas - antigas  # o que o arquivo novo tem e a fatura guardada ainda não


def salvar(f: Fatura, uid: int) -> tuple[int, int | None]:
    """Grava a fatura. Devolve (id, None) para fatura nova ou (id, n) quando o arquivo era uma versão mais completa de uma
    fatura já importada e só os n lançamentos novos foram acrescentados."""
    h = _hash_do_usuario(uid, f.hash)
    with conn() as c:
        if (r := c.execute("SELECT id FROM faturas WHERE hash=?", (h,)).fetchone()):
            raise Duplicada(r["id"])
        achada = _parecida(c, f, uid)
        if achada:
            fid, faltam = achada
            if not faltam:
                raise Duplicada(fid)  # o arquivo novo é igual ou mais curto do que já está guardado
            novos = []
            for t in f.txs:
                k = (t.data.isoformat(), t.descricao, t.bruto_cents)
                if faltam.get(k, 0) > 0:
                    faltam[k] -= 1
                    novos.append(t)
            _inserir_txs(c, fid, novos)
            atual = c.execute("SELECT * FROM faturas WHERE id=?", (fid,)).fetchone()
            avisos = json.loads(atual["avisos"] or "[]")
            avisos.append(f"Atualizada com {len(novos)} lançamento(s) novo(s) de um arquivo mais recente.")
            ref = max(atual["referencia"], f.referencia.isoformat()) if not atual["vencimento"] else atual["referencia"]
            fech = max(x for x in (atual["fechamento"], _iso(f.fechamento)) if x) if (atual["fechamento"] or f.fechamento) else None
            c.execute("UPDATE faturas SET avisos=?, referencia=?, fechamento=?, origem=COALESCE(origem, ?) WHERE id=?",
                      (json.dumps(avisos, ensure_ascii=False), ref, fech, f.origem, fid))
            _refazer(c, c.execute("SELECT * FROM faturas WHERE id=?", (fid,)).fetchone(), f.total_cents, None)
            return fid, len(novos)
        try:
            cur = c.execute(
                """INSERT INTO faturas (usuario_id, emissor, vencimento, fechamento, referencia, total_cents, soma_cents,
                   diff_cents, status, formato, arquivo, hash, avisos, conta, origem) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, f.emissor, _iso(f.vencimento), _iso(f.fechamento), f.referencia.isoformat(), f.total_cents,
                 f.soma_cents, f.diff_cents, f.status, f.formato, f.arquivo, h,
                 json.dumps(f.avisos, ensure_ascii=False), int(f.conta), f.origem),
            )
        except sqlite3.IntegrityError:  # duas importações iguais ao mesmo tempo: a segunda perde a corrida
            c.rollback()
            r = c.execute("SELECT id FROM faturas WHERE hash=?", (h,)).fetchone()
            raise Duplicada(r["id"] if r else 0) from None
        fid = cur.lastrowid
        _inserir_txs(c, fid, f.txs)
        return fid, None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _cab(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["avisos"] = json.loads(d.get("avisos") or "[]")
    d["conta"] = bool(d.get("conta"))
    for interno in ("hash", "usuario_id", "origem"):
        d.pop(interno, None)
    return d


def listar(uid: int) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """SELECT f.*, (SELECT COUNT(*) FROM transacoes t WHERE t.fatura_id=f.id) AS n_transacoes
               FROM faturas f WHERE f.usuario_id=? ORDER BY f.referencia DESC, f.id DESC""", (uid,)
        ).fetchall()
        return [_cab(r) for r in rows]


def _reconciliacao(c: sqlite3.Connection, fid: int, cab: dict) -> dict:
    por_tipo = {r["tipo"]: r["s"] for r in c.execute(
        "SELECT tipo, SUM(valor_cents) AS s FROM transacoes WHERE fatura_id=? GROUP BY tipo", (fid,))}
    return {
        "compras_cents": por_tipo.get("compra", 0), "encargos_cents": por_tipo.get("encargo", 0),
        "saldo_anterior_cents": por_tipo.get("saldo_anterior", 0), "estornos_cents": por_tipo.get("estorno", 0),
        "pagamentos_cents": por_tipo.get("pagamento", 0), "entradas_cents": por_tipo.get("entrada", 0),
        "internos_cents": por_tipo.get("interno", 0), "soma_cents": cab["soma_cents"],
        "total_cents": cab["total_cents"], "diff_cents": cab["diff_cents"], "status": cab["status"],
    }


def obter(fid: int, uid: int) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM faturas WHERE id=? AND usuario_id=?", (fid, uid)).fetchone()
        if not r:
            return None
        d = _cab(r)
        d["reconciliacao"] = _reconciliacao(c, fid, d)
        d["transacoes"] = [dict(t) for t in c.execute(
            """SELECT id, data, descricao, valor_cents, tipo, parcela_atual, parcela_total, categoria
               FROM transacoes WHERE fatura_id=? ORDER BY data, id""", (fid,))]
        return d


def excluir(fid: int, uid: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM faturas WHERE id=? AND usuario_id=?", (fid, uid)).rowcount > 0


def _refazer(c: sqlite3.Connection, f: sqlite3.Row, total_cents: int | None, vencimento: date | None) -> None:
    """Reclassifica os lançamentos e refaz soma, diferença e status de uma fatura."""
    fid = f["id"]
    rows = c.execute("SELECT * FROM transacoes WHERE fatura_id=?", (fid,)).fetchall()
    raws = [RawTx(data=date.fromisoformat(r["data"]), descricao=r["descricao"], bruto_cents=r["bruto_cents"],
                  fitid=r["fitid"]) for r in rows]
    regras = {x["chave"]: x["categoria"] for x in c.execute("SELECT chave, categoria FROM regras WHERE usuario_id=?", (f["usuario_id"],))}
    if f["conta"]:
        pares = [(raw, tipo_conta(raw)) for raw in raws]
        total, soma, diff, status = None, soma_saidas_cents(pares), None, "sem_total"
    else:
        total = total_cents if total_cents is not None else f["total_cents"]
        sinal, _ = escolher_convencao(raws, total, padrao_ofx=f["formato"] == "ofx")
        pares = _classificar(raws, sinal)
        soma = soma_cents(pares)
        if total is None:
            diff, status = None, "sem_total"
        else:
            diff = soma - total
            status = "ok" if abs(diff) <= 1 else "divergente"
    for r, (_, tipo) in zip(rows, pares):
        if tipo != r["tipo"]:
            c.execute("UPDATE transacoes SET tipo=?, valor_cents=?, categoria=? WHERE id=?",
                      (tipo, abs(r["bruto_cents"]), categorizar(r["descricao"], tipo, None, regras), r["id"]))
    venc = _iso(vencimento) or f["vencimento"]
    ref = venc or f["referencia"]
    c.execute("UPDATE faturas SET total_cents=?, soma_cents=?, diff_cents=?, status=?, vencimento=?, referencia=? WHERE id=?",
              (total, soma, diff, status, venc, ref, fid))


def atualizar_total(fid: int, uid: int, total_cents: int | None, vencimento: date | None) -> dict | None:
    """Informa total/vencimento depois do import e refaz a conferência (inclusive a convenção de sinal)."""
    with conn() as c:
        f = c.execute("SELECT * FROM faturas WHERE id=? AND usuario_id=?", (fid, uid)).fetchone()
        if not f:
            return None
        _refazer(c, f, total_cents, vencimento)
    return obter(fid, uid)


def trocar_categoria(tx_id: int, uid: int, categoria: str) -> dict | None:
    with conn() as c:
        t = c.execute("""SELECT t.id, t.chave, t.categoria, t.tipo FROM transacoes t JOIN faturas f ON f.id=t.fatura_id
                         WHERE t.id=? AND f.usuario_id=?""", (tx_id, uid)).fetchone()
        if not t:
            return None
        if t["tipo"] not in ("compra", "estorno"):
            raise TipoFixo()
        suas = "fatura_id IN (SELECT id FROM faturas WHERE usuario_id=?)"
        parecidas = c.execute(
            f"SELECT id, categoria FROM transacoes WHERE chave=? AND categoria<>? AND tipo IN ('compra','estorno') AND {suas}",
            (t["chave"], categoria, uid)).fetchall()
        anteriores = [{"id": r["id"], "categoria": r["categoria"]} for r in parecidas]
        if t["id"] not in {a["id"] for a in anteriores} and t["categoria"] != categoria:
            anteriores.append({"id": t["id"], "categoria": t["categoria"]})
        c.execute(f"UPDATE transacoes SET categoria=? WHERE chave=? AND tipo IN ('compra','estorno') AND {suas}",
                  (categoria, t["chave"], uid))
        c.execute("UPDATE transacoes SET categoria=? WHERE id=?", (categoria, t["id"]))
        c.execute("INSERT INTO regras (usuario_id, chave, categoria) VALUES (?,?,?) "
                  "ON CONFLICT(usuario_id, chave) DO UPDATE SET categoria=excluded.categoria", (uid, t["chave"], categoria))
        return {"atualizadas": len(anteriores), "anteriores": anteriores, "chave": t["chave"],
                "categoria_anterior": t["categoria"], "categoria": categoria}


def restaurar(uid: int, itens: list[dict], chave_regra: str, categoria_regra: str) -> bool:
    """Desfaz uma troca de categoria. Só aceita a chave de um estabelecimento que existe (ou que já tem regra): sem isso
    qualquer chamada poderia gravar regras arbitrárias."""
    with conn() as c:
        if not c.execute(
                """SELECT 1 FROM transacoes t JOIN faturas f ON f.id=t.fatura_id WHERE t.chave=? AND f.usuario_id=?
                   UNION SELECT 1 FROM regras WHERE chave=? AND usuario_id=? LIMIT 1""",
                (chave_regra, uid, chave_regra, uid)).fetchone():
            return False
        c.executemany("UPDATE transacoes SET categoria=? WHERE id=? AND fatura_id IN (SELECT id FROM faturas WHERE usuario_id=?)",
                      [(i["categoria"], i["id"], uid) for i in itens])
        c.execute("INSERT INTO regras (usuario_id, chave, categoria) VALUES (?,?,?) "
                  "ON CONFLICT(usuario_id, chave) DO UPDATE SET categoria=excluded.categoria", (uid, chave_regra, categoria_regra))
        return True


def _gasto_fatura(c: sqlite3.Connection, fid: int) -> int:
    return c.execute(f"SELECT COALESCE({GASTO},0) AS g FROM transacoes WHERE fatura_id=?", (fid,)).fetchone()["g"]


def _origem(f: sqlite3.Row) -> str:
    return f["emissor"] or f["origem"] or ""


def resumo(fid: int | None, uid: int) -> dict | None:
    with conn() as c:
        if fid is None:
            r = c.execute("SELECT id FROM faturas WHERE usuario_id=? ORDER BY referencia DESC, id DESC LIMIT 1", (uid,)).fetchone()
            if not r:
                return None
            fid = r["id"]
        f = c.execute("SELECT * FROM faturas WHERE id=? AND usuario_id=?", (fid, uid)).fetchone()
        if not f:
            return None
        cats = [dict(r) for r in c.execute(
            f"""SELECT categoria AS nome, {GASTO} AS total_cents, COUNT(*) AS qtd FROM transacoes
                WHERE fatura_id=? AND tipo IN ('compra','encargo','estorno') GROUP BY categoria
                HAVING {GASTO} > 0 ORDER BY total_cents DESC""", (fid,))]
        maiores = [dict(r) for r in c.execute(
            """SELECT id, data, descricao, valor_cents, categoria, parcela_atual, parcela_total FROM transacoes
               WHERE fatura_id=? AND tipo='compra' ORDER BY valor_cents DESC LIMIT 5""", (fid,))]
        ant = c.execute(
            f"""SELECT id, referencia, vencimento FROM faturas WHERE usuario_id=? AND conta=? AND {ORIGEM}=?
                AND (referencia < ? OR (referencia = ? AND id < ?)) ORDER BY referencia DESC, id DESC LIMIT 1""",
            (uid, f["conta"], _origem(f), f["referencia"], f["referencia"], fid)).fetchone()
        anterior = None
        if ant:
            anterior = {"id": ant["id"], "referencia": ant["referencia"], "vencimento": ant["vencimento"],
                        "gasto_cents": _gasto_fatura(c, ant["id"])}
        return {"fatura_id": fid, "gasto_cents": _gasto_fatura(c, fid), "categorias": cats,
                "maiores": maiores, "anterior": anterior}


def parcelas_futuras(uid: int) -> dict:
    """Projeta parcelas restantes a partir da fatura mais recente de cada cartão. Cartão = nome informado ou, sem nome,
    a assinatura do arquivo (OFX: banco e conta; CSV: colunas), para não misturar cartões diferentes."""
    with conn() as c:
        ultimas: dict[str, sqlite3.Row] = {}
        for f in c.execute("SELECT * FROM faturas WHERE usuario_id=? AND conta=0 ORDER BY referencia DESC, id DESC", (uid,)):
            ultimas.setdefault(_origem(f), f)
        meses: dict[str, dict] = {}
        for f in ultimas.values():
            base = date.fromisoformat(f["vencimento"] or f["referencia"])
            for t in c.execute(
                """SELECT descricao, valor_cents, parcela_atual, parcela_total FROM transacoes
                   WHERE fatura_id=? AND tipo='compra' AND parcela_atual IS NOT NULL AND parcela_atual < parcela_total""",
                    (f["id"],)):
                for k in range(1, t["parcela_total"] - t["parcela_atual"] + 1):
                    mes_idx = base.year * 12 + (base.month - 1) + k
                    chave_mes = f"{mes_idx // 12:04d}-{mes_idx % 12 + 1:02d}"
                    m = meses.setdefault(chave_mes, {"mes": chave_mes, "total_cents": 0, "itens": []})
                    m["total_cents"] += t["valor_cents"]
                    m["itens"].append({"descricao": t["descricao"], "valor_cents": t["valor_cents"],
                                       "parcela": f"{t['parcela_atual'] + k}/{t['parcela_total']}",
                                       "emissor": f["emissor"]})
        lista = [meses[k] for k in sorted(meses)]
        for m in lista:
            m["itens"].sort(key=lambda i: -i["valor_cents"])
        return {"total_cents": sum(m["total_cents"] for m in lista), "meses": lista}
