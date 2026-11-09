# Como rodar a Maré em desenvolvimento (Windows)

Passo a passo para sair do zero e ver o app funcionando em http://localhost:8000.
Os comandos são para o **PowerShell**, dentro da pasta do projeto.

## 1. O que você precisa ter instalado

| Programa | Versão | Conferir com |
|---|---|---|
| Python | 3.11 ou mais novo | `python --version` |
| Node.js (inclui o npm) | 20 ou mais novo | `node --version` |

Python roda o backend (FastAPI + SQLite). Node só compila o frontend, que é escrito em TypeScript.

> **Se o `npm` der erro de "execução de scripts desabilitada"**, é a política do PowerShell, não o projeto.
> Resolva uma vez com `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`,
> ou use `npm.cmd` no lugar de `npm` em todos os comandos abaixo.

## 2. Instalar (só na primeira vez)

```powershell
# 1) ambiente virtual do Python (pasta .venv)
python -m venv .venv

# 2) dependências do backend
.venv\Scripts\python -m pip install -r requirements.txt

# 3) dependências do frontend (esbuild e typescript)
npm install
```

Não precisa "ativar" o ambiente virtual: nos comandos abaixo chamamos `.venv\Scripts\python` direto.

> **Se o passo 1 falhar com "Unable to copy ... venvlauncher.exe"**, o `.venv` já existe e o `python.exe` dele está em uso
> (normalmente por um `uvicorn` rodando). Pule o passo 1 e siga para o 2. Para recriar do zero, pare o servidor com
> `Ctrl+C`, rode `Remove-Item -Recurse -Force .venv` e crie de novo.

## 3. Gerar o frontend

```powershell
npm run build
```

Isso cria `static/dist/main.js`. Essa pasta não vai para o git, então **depois de clonar o projeto o build é obrigatório**: sem ele a página abre em branco.

## 4. Subir em modo dev

Abra **dois terminais** na pasta do projeto e deixe os dois rodando.

**Terminal 1: recompila o frontend a cada alteração em `frontend/src`**

```powershell
npm run dev
```

**Terminal 2: backend, com recarga automática ao mudar o código Python**

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
```

Quando aparecer `Uvicorn running on http://127.0.0.1:8000`, abra **http://localhost:8000**.
Depois de mexer no frontend, basta atualizar a página (F5). O terminal 1 não abre porta nenhuma, só recompila.

Para parar, use `Ctrl+C` em cada terminal.

## 5. Primeiro acesso

1. A primeira tela é a de acesso. Escolha criar conta e preencha nome, e-mail e senha.
2. A **primeira conta adota os dados que já estiverem em `data/mare.db`**. Se você já importou faturas antes de existir login, elas aparecem nessa conta.
3. Depois da primeira conta, o cadastro fica fechado. Para liberar mais pessoas, veja `CADASTRO_ABERTO` na seção 6.

Sem nenhum `.env`, o cadastro é direto: não pede código por e-mail.

## 6. Configuração opcional (`.env`)

Para o dia a dia de desenvolvimento **você não precisa de `.env`**. Só crie se quiser mudar algo.

> **O nome do arquivo é `.env`, com o ponto na frente.** Se salvar como `env`, o app ignora tudo sem avisar.
> O `.env.example` pode ser copiado como ponto de partida: ele vem com `CONFIRMAR_EMAIL=0` e o SMTP comentado.

Crie um arquivo `.env` na raiz do projeto, com uma variável por linha. As mais úteis:

| Variável | Padrão | Para que serve |
|---|---|---|
| `DB_PATH` | `data/mare.db` | Onde o SQLite fica salvo. Use outro caminho para testar sem mexer nos seus dados. |
| `CADASTRO_ABERTO` | `0` | `1` permite criar contas além da primeira. |
| `ALLOWED_HOSTS` | só localhost | Nomes ou IPs extras aceitos, por exemplo `192.168.0.10` para abrir pelo celular na mesma rede. |
| `MAX_UPLOAD_MB` | `5` | Tamanho máximo do arquivo da fatura. |
| `MAX_LINHAS` | `3000` | Máximo de lançamentos por arquivo. |
| `SESSAO_DIAS` | `14` | Validade do login. |

Depois de editar o `.env`, reinicie o `uvicorn` (a recarga automática só vigia o código, não o `.env`).

### Confirmação de e-mail por código (opcional)

Com `CONFIRMAR_EMAIL=1`, a conta só passa a existir depois que a pessoa digita o código de 6 números enviado por e-mail. Exige SMTP configurado (`SMTP_HOST`, `SMTP_PORTA`, `SMTP_USUARIO`, `SMTP_SENHA`, `SMTP_REMETENTE`, `SMTP_SEGURANCA`). O `.env.example` explica, linha a linha, como pegar esses dados no Brevo.

> **Erro comum:** `SMTP_SENHA` precisa ser a **chave SMTP** (começa com `xsmtpsib-`), gerada na aba **SMTP** em *Generate a new SMTP key*.
> Uma chave de API (`xkeysib-...`, da aba "Chaves API") é recusada com `535 Authentication failed`, e a tela mostra "Não consegui enviar o e-mail agora".
> O `SMTP_USUARIO` é o Login mostrado nessa mesma aba (algo como `abc123@smtp-brevo.com`), e o `SMTP_REMETENTE` precisa estar verificado em *Senders*.

Para testar **sem servidor de e-mail real**, rode um coletor local num terceiro terminal (o código aparece nele):

```powershell
.venv\Scripts\python -m pip install aiosmtpd
.venv\Scripts\python -m aiosmtpd -n -l 127.0.0.1:2525
```

e use no `.env`:

```
CONFIRMAR_EMAIL=1
SMTP_HOST=127.0.0.1
SMTP_PORTA=2525
SMTP_SEGURANCA=nenhuma
SMTP_REMETENTE=mare@exemplo.com
```

## 7. Importar uma fatura

1. Entre em **Faturas**.
2. Escolha o arquivo **OFX** (preferido, já traz o total) ou **CSV** da fatura do cartão. PDF e Excel não são aceitos.
3. A Maré soma os lançamentos e confere com o total. Veja o resultado em **Resumo** e a lista em **Transações**.

## 8. Conferir que está tudo certo

```powershell
.venv\Scripts\python -m pytest     # testes do backend
npm run check                      # tipos do frontend (modo estrito) + build
```

## 9. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `npm` bloqueado, "execução de scripts desabilitada" | Política do PowerShell. Veja o aviso na seção 1. |
| Página em branco | Falta `static/dist/main.js`. Rode `npm run build`. |
| Mudei o frontend e nada mudou | Confirme que `npm run dev` está rodando e force o recarregamento com `Ctrl+F5`. O app é um PWA com cache: se persistir, F12 > Application > Storage > Clear site data. |
| `address already in use` ou porta 8000 ocupada | Já existe outro servidor nela. Feche o outro terminal ou suba com `--port 8001` e abra http://localhost:8001. |
| O servidor nem sobe e reclama de SMTP | `CONFIRMAR_EMAIL=1` sem SMTP configurado. Veja a seção 6. |
| Acesso recusado ao abrir por IP ou outro nome | O app só aceita `localhost`, `127.0.0.1` e `[::1]`. Liste o nome ou IP em `ALLOWED_HOSTS` no `.env` e reinicie. |
| "Cadastro fechado" | Já existe uma conta. Use `CADASTRO_ABERTO=1` no `.env` para criar outras. |
| Quero começar do zero | Pare o servidor e apague `data/mare.db` (faça uma cópia antes se tiver faturas importantes). Ele é recriado na próxima subida. |

## 10. Onde está cada coisa

```
app/        backend: leitura de OFX/CSV, conferência, categorias, contas, SQLite, API
frontend/   código-fonte do app em TypeScript (src/) e o build (build.mjs)
static/     o que o backend serve: HTML, CSS, fontes, ícones, service worker; dist/ é gerado pelo build
tests/      testes do backend, com arquivos de exemplo
data/       banco SQLite (mare.db), não versionado
docs/       esta documentação
```
