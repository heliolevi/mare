# Maré

Organizador de finanças pessoais com foco em fatura de cartão de crédito. Você importa o arquivo **OFX** ou **CSV** da fatura, a Maré soma os lançamentos, confere com o total do banco e mostra para onde o dinheiro foi. É um PWA servido por um backend FastAPI com SQLite.

Nada sai da sua máquina: o arquivo é lido no servidor e descartado, e só os lançamentos ficam no banco. Não há chave de API nem serviço externo.

## O que precisa

- Python 3.11 ou mais novo
- Node 20 ou mais novo (só para compilar o frontend em TypeScript)
- `pip install -r requirements.txt` (fastapi, uvicorn, python-multipart; pytest e httpx só para os testes)
- `npm install` (esbuild e typescript, só em desenvolvimento)

## Rodar

```bash
pip install -r requirements.txt
npm install
npm run build          # gera static/dist/main.js a partir de frontend/src
uvicorn app.main:app --port 8000
```

Abra http://localhost:8000. A primeira tela é a de acesso: crie a sua conta (a primeira conta adota qualquer dado que já estivesse no banco) e entre. Em produção, suba com `uvicorn app.main:app --no-server-header`, para o servidor não anunciar o nome e a versão.

### Desenvolvimento

Em dois terminais:

```bash
npm run dev                                  # recompila o frontend a cada alteração
uvicorn app.main:app --port 8000 --reload    # backend com recarga
```

`npm run typecheck` confere os tipos (modo estrito). `npm run check` faz a conferência e o build.
`static/dist/` não é versionado: rode `npm run build` depois de clonar e antes de subir em produção.

Testes do backend: `python -m pytest`

### Contas e sessões

- Cada pessoa tem a sua conta e só vê as próprias faturas e regras de categoria. A senha é guardada com scrypt (parâmetros do OWASP); o servidor nunca guarda a senha nem o token de sessão em texto, só os hashes.
- A sessão é um cookie `HttpOnly`, `SameSite=Strict` (e `Secure` quando o acesso é por HTTPS), renovado a cada uso e válido por 14 dias (`SESSAO_DIAS`). O JavaScript do app não enxerga o token e nada de sensível vai para o `localStorage`.
- Depois da primeira conta, o cadastro fica fechado. Para abrir para mais gente, defina `CADASTRO_ABERTO=1` no `.env`.
- Tentativas de login e de cadastro, e envios de arquivo (`UPLOADS_POR_MINUTO`, padrão 10 por pessoa), têm limite de taxa. Os contadores ficam na memória do processo; se rodar com vários processos, o limite vale por processo.
- Em breve: e-mail de confirmação na criação da conta. A tela de cadastro já avisa disso; por enquanto não há envio de e-mail e quem cria a conta já entra.
- Reimportar uma fatura mais completa do mesmo cartão (mesmo emissor, vencimento próximo, mesmas linhas mais algumas novas) atualiza a fatura existente e só acrescenta os lançamentos novos, em vez de duplicar.

### Segurança e limites

- O app só responde a `localhost`, `127.0.0.1` e `[::1]`. Para abrir por outro nome ou IP, defina `ALLOWED_HOSTS` no `.env`.
- Requisições de escrita vindas de outro site (cabeçalho `Origin` diferente do host) são recusadas.
- Limites: `MAX_UPLOAD_MB` (padrão 5) e `MAX_LINHAS` (padrão 3000) por arquivo; valores acima de R$ 10 bilhões e datas fora de 2000–2100 são rejeitados.
- Extratos de conta (OFX bancário) são lidos como extrato: só as saídas contam como gasto; entradas, pagamento de fatura e aplicações ficam à parte.
- O banco é migrado sozinho na primeira subida (`PRAGMA user_version`). Faça uma cópia de `data/mare.db` antes de atualizar.
- A documentação automática da API (`/docs`, `/openapi.json`) fica desligada, e `static/dist` sai sem source map.

## Como baixar o arquivo no banco

Abra a fatura do cartão no app ou no site do banco e procure **Exportar** ou **Baixar fatura**. Prefira OFX, que já traz o total da fatura. Se o banco só oferecer CSV, a Maré aceita e você informa o total à mão para a conferência. PDF e planilhas do Excel não são aceitos.

A cobertura depende de o seu banco oferecer exportação. O formato nativo de exportação do Nubank não foi confirmado, então teste com o seu arquivo real.

## O que o app faz

- **Conferência:** soma compras, encargos e saldo anterior, desconta estornos e compara com o total. Mostra Conferido, Divergente ou Sem total.
- **Transações:** busca, filtro por categoria e troca de categoria com "Desfazer". A troca vale para lançamentos parecidos, inclusive em faturas futuras.
- **Parcelas:** projeta as parcelas que ainda vão vencer, mês a mês, a partir da fatura mais recente de cada cartão.
- **Faturas:** importa, lista e exclui.
- **Páginas de erro:** endereços inexistentes mostram uma página 404 da Maré (no servidor e dentro do app); a API responde 404 em JSON.

## Estrutura

```
app/        backend: leitura de OFX/CSV, conferência, categorias, SQLite, API
frontend/   código-fonte do app em TypeScript (src/), tipos da API em src/types.ts e build.mjs (esbuild)
static/     PWA servido pelo backend (HTML, CSS, service worker, manifest, logo); static/dist é gerado pelo build
tests/      testes do backend com arquivos de exemplo
tools/      gerador dos ícones PNG do PWA a partir do logo
DESIGN.md   decisões visuais
```

## Próximos passos possíveis

Fallback de PDF para bancos sem OFX/CSV, e Open Finance via agregador (os preços dos agregadores precisam ser confirmados com cada fornecedor).
