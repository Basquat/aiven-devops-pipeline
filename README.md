# Pipeline DevOps — Dashboard + Aiven.io

Laboratório de Cloud Computing & DevOps: um dashboard Flask com indicadores
econômicos do Banco Central, dados guardados num **PostgreSQL gerenciado pela
Aiven.io**, e um pipeline de CI/CD no **GitHub Actions** que:

1. Provisiona o Postgres na Aiven via **Terraform** (rodando no runner do GitHub).
2. Roda lint e testes da aplicação contra um Postgres descartável.
3. Builda e publica a imagem Docker no GitHub Container Registry (GHCR).
4. Dispara o deploy no **Render** e só fica verde quando a versão nova está no ar.

Tudo pelo navegador (GitHub, Aiven e Render), sem instalar nada na máquina.

Esta versão cobre só o **laboratório básico**. Kafka e Grafana foram tirados
porque são pagos na Aiven (ver [Mudanças em relação ao original](#mudanças-em-relação-ao-original)).

## Estrutura

```
├── Dockerfile               # fica na raiz, copia de app/ (ver Troubleshooting 1)
├── app/
│   ├── app.py               # rotas Flask: /, /api/indicators, /api/refresh, /healthz
│   ├── bcb_client.py        # pool de conexões com o Postgres + client da API do BCB
│   ├── test_app.py          # testes (rodam no CI com Postgres em container)
│   ├── requirements.txt
│   ├── .env.example
│   ├── templates/dashboard.html
│   └── static/style.css
├── terraform/               # Postgres na Aiven (plano free)
└── .github/workflows/
    ├── infra.yml            # Terraform (manual)
    ├── ci-cd.yml            # test → build/push → deploy
    └── refresh-data.yml     # atualiza os dados do BCB a cada 6h
```

## Passo a passo

Segue as 10 etapas do guia do professor, com os ajustes que este código precisa.

### 1. Conta e projeto na Aiven
Crie a conta em [aiven.io](https://aiven.io) e um **Project** (ex.: `turma-devops-2026`).
Anote o nome exato.

### 2. Token de API
Avatar → **Profile → Authentication tokens → Generate token**. Copie na hora,
ele não aparece de novo.

### 3. Repositório no GitHub
Faça um fork deste repositório ou suba os arquivos num repositório seu.
A aba **Actions** deve listar os workflows.

### 4. Secrets
Em **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Valor |
|---|---|
| `AIVEN_API_TOKEN` | token da etapa 2 |
| `AIVEN_PROJECT` | nome do projeto da etapa 1 |
| `RENDER_DEPLOY_HOOK_URL` | deploy hook do Render (etapa 8) |
| `APP_HEALTHCHECK_URL` | URL pública do app, ex.: `https://seu-app.onrender.com` (sem `/` no final) |

Enquanto os dois últimos estiverem vazios, o pipeline não falha: ele pula o
deploy com um aviso.

### 5. Provisionar o Postgres
**Actions → Infra - Provisionar Aiven (Terraform) → Run workflow.**
Quando terminar, no console da Aiven: **Services → dashboard-pg**, status
*Running*. Em **Connection information**, copie a **Service URI**.

O plano usado é o `free-1-1gb` (gratuito). **Não troque por `hobbyist`**: ele é
cobrado. Pode rodar o workflow de novo sem medo: ele reconhece o serviço que já
existe em vez de tentar criar outro.

### 6. Serviço no Render
[render.com](https://render.com) → **New → Web Service** → conecte o repositório.

- **Runtime**: Docker
- **Root Directory**: **vazio** (o guia em PDF diz `app`, mas aqui o Dockerfile
  fica na raiz e com `app` o build quebra)
- **Instance type**: Free

### 7. Variáveis de ambiente no Render
Em **Environment**:

- `AIVEN_DB_URL`: a Service URI da etapa 5.
- `PORT`: `8080` (opcional, o container escuta na porta que o Render mandar).

Crie o serviço, espere o primeiro deploy e copie a URL pública para o secret
`APP_HEALTHCHECK_URL`.

Duas configurações que valem a pena em **Settings**:

- **Health Check Path** = `/healthz`. O Render só troca para a versão nova se
  ela responder ok, então um deploy quebrado não derruba o site.
- **Auto-Deploy** = **Off**. Assim só o pipeline faz deploy, e só depois dos
  testes passarem. Com Auto-Deploy ligado, cada push faz dois deploys (o
  automático e o do hook) e código que quebrou no teste vai para o ar do mesmo jeito.

### 8. Deploy hook
No Render, **Settings → Deploy Hook**: copie a URL para o secret
`RENDER_DEPLOY_HOOK_URL`.

### 9. Rodar o CI/CD
Qualquer push em `app/` na `main` dispara o **CI/CD - Dashboard App**. Também
dá para rodar pelo botão *Run workflow*. Os três jobs:

1. **test**: flake8 e `test_app.py` contra um Postgres 16 em container.
2. **build-and-push**: imagem em `ghcr.io/<usuário>/<repo>/dashboard-app`.
3. **deploy**: chama o hook e consulta `/healthz` até ele responder com o
   commit do push (até 10 min, o free tier do Render é lento para subir).

Em pull request só roda o `test`.

### 10. Validar
Abra a URL pública. A página recarrega sozinha a cada 10 s, e cada carga conta
como um acesso:

- card "Acessos ao dashboard" aumentando;
- gráfico de acessos por minuto (últimos 30 min);
- tabela "Últimos acessos";
- cards e gráfico com dólar, Selic e IPCA.

## Fonte de dados: Banco Central (SGS)

API pública, sem chave: [dadosabertos.bcb.gov.br](https://dadosabertos.bcb.gov.br/).

| Código | Indicador | Unidade |
|---|---|---|
| 1 | Dólar comercial (venda) | R$ |
| 432 | Meta Selic (Copom) | % a.a. |
| 433 | IPCA — variação mensal | % |

Cada série fica em cache na tabela `bcb_series`. A cada visita o app confere se
o cache tem mais de `CACHE_HOURS` (padrão 6h) e só então busca na API. Se a API
do BCB cair, o app continua mostrando o último dado salvo. Para trocar ou
adicionar séries, edite o dicionário `SERIES` em `bcb_client.py` (catálogo em
[www3.bcb.gov.br/sgspub](https://www3.bcb.gov.br/sgspub)).

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `AIVEN_DB_URL` | sim | Service URI do Postgres da Aiven |
| `PORT` | não | porta HTTP (padrão 8080; o Render define a dele) |
| `CACHE_HOURS` | não | horas de cache das séries do BCB (padrão 6) |
| `TZ_DISPLAY` | não | fuso usado nos horários de acesso (padrão `America/Sao_Paulo`) |
| `DB_SSLMODE` | não | só para teste local/CI (`disable`); em produção fica `require` |

## Rodando os testes local (opcional)

Precisa de um Postgres local, por exemplo com Docker:

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
cd app
pip install -r requirements.txt
AIVEN_DB_URL=postgres://postgres:postgres@localhost:5432/postgres DB_SSLMODE=disable \
  python -m unittest -v test_app
```

## Mudanças em relação ao original

- **Kafka e Grafana removidos** (Terraform, `producer.py`, `consumer.py`,
  `kafka_common.py` e os dois workflows). Ficam pagos na Aiven e não fazem
  parte do lab básico. Estão no primeiro commit do histórico se alguém quiser
  fazer a extensão.
- **Plano do Postgres**: `hobbyist` → `free-1-1gb`. O `hobbyist` é cobrado. Saíram
  também o `aiven_pg_database` e o `aiven_pg_user`, que o app não usava (ele
  conecta com o `avnadmin` no `defaultdb` da Service URI).
- **infra.yml**: só manual, confere os secrets antes e importa o serviço se já
  existir. Antes, rodar duas vezes dava erro de "already exists", porque o state
  do Terraform some no fim de cada job.
- **Bug no gráfico**: a consulta das séries usava `ORDER BY ref_date ASC LIMIT 30`,
  ou seja, pegava os 30 pontos **mais antigos** da tabela. Como a tabela só
  cresce, com o tempo o dashboard parava de mostrar o dado atual. Agora pega os
  mais recentes.
- **Dashboard**: gráfico de acessos por minuto, tabela de últimos acessos e
  recarga a cada 10 s, como pede a etapa 10 do guia. As séries viraram um
  gráfico cada: antes as três dividiam o eixo de datas do dólar, então o IPCA
  (mensal) aparecia em datas erradas e, se o dólar falhasse, o gráfico sumia todo.
- **IPCA com só 3 pontos**: a busca pegava os últimos `30 × 3` dias, o que
  numa série mensal dá 3 meses. Séries mensais agora buscam 30 meses.
- **API do BCB instável**: às vezes ela derruba a conexão sem motivo (aconteceu
  testando). As chamadas agora tentam de novo até 3 vezes antes de desistir.
- **Testes de verdade no CI**: antes era só `py_compile` e o flake8 com
  `--exit-zero` (nunca falhava). Agora o flake8 reprova e o `test_app.py` roda
  contra um Postgres em container, com a API do BCB simulada.
- **Deploy confiável**: o `sleep 45` + um `curl` passava mesmo com a versão
  antiga no ar. Agora o `/healthz` devolve o commit (`RENDER_GIT_COMMIT`) e o job
  espera a versão certa. Sem os secrets do Render o deploy é pulado com aviso.
  Também tem `workflow_dispatch`, `concurrency` e cache de pip e de camadas Docker.
- **Dockerfile**: roda como usuário sem privilégio, escuta em `$PORT` (acaba com
  o problema de porta do item 8 do Troubleshooting), logs sem buffer e
  `--threads 4` para uma requisição lenta não travar as outras.
- **/healthz** não devolve mais a mensagem de erro do banco para quem acessa
  (ela mostrava host e usuário). O detalhe vai para o log do Render.
- `.gitignore` e `.dockerignore` adicionados.

## Troubleshooting

Problemas reais de quando o projeto foi colocado no ar pela primeira vez.

**1. Build falha em `COPY requirements.txt .` / `not found`.**
O Dockerfile estava em `app/` e o contexto de build do Render era a raiz. Por
isso ele foi movido para a raiz, com `COPY app/...`. Deixe o **Root Directory vazio**.

**2. `COPY` ou `import` falha mesmo com o arquivo "lá".**
Confira se o nome não tem espaço sobrando (já aconteceu com ` requirements.txt`
e com o `bcb_client.py`, ao renomear pelo editor web do GitHub). Para
diagnosticar, um `RUN find . -maxdepth 3 -not -path '*/.git*'` temporário no
Dockerfile mostra o que chegou no build.

**3. `relation "..." does not exist`.**
O `init_db()` precisa rodar no import do módulo, não só no
`if __name__ == "__main__"`, porque o gunicorn nunca executa esse bloco. Já está assim.

**4. `UniqueViolation ... pg_type_typname_nsp_index` na subida.**
Dois workers criando a mesma tabela ao mesmo tempo. É inofensivo e o
`init_db()` já ignora.

**5. API do BCB devolvendo 400.**
O endpoint `/dados/ultimos/{n}` passou a dar 400. O código usa `/dados` com
`dataInicial`/`dataFinal` e recorta os últimos N pontos.

**6. Página carrega para sempre.**
Era vazamento de conexão (`with conn:` não fecha a conexão). Hoje tem pool
(`ThreadedConnectionPool`) e `connect_timeout=10`. O free da Aiven aceita no
máximo 20 conexões; o pool usa até 5.

**7. Render diz "live", mas dá 502 / `No open HTTP ports detected`.**
Porta do gunicorn diferente da que o Render espera. Com o Dockerfile atual
(escutando em `$PORT`) isso não deve mais acontecer. Se acontecer, crie
`PORT=8080` em Environment.

**8. `/healthz` dá erro / deploy não fica verde.**
Veja o log do serviço no Render. Normalmente é `AIVEN_DB_URL` errada ou sem
`?sslmode=require`. Confira também se o allowlist de IP do Postgres na Aiven
permite `0.0.0.0/0`.

**9. `terraform apply` falha com 401/403.**
Token inválido ou de outro projeto. Gere um novo e confira `AIVEN_PROJECT`.

**10. Workflow não aparece em Actions.**
O YAML tem que estar exatamente em `.github/workflows/`.

**11. Postgres da Aiven desligado sozinho.**
A Aiven pode desligar serviço free parado. O `refresh-data.yml` mantém alguma
atividade a cada 6h. Se desligar mesmo assim, ligue de novo pelo console.

## Diagrama

```
 push em app/                         Run workflow (manual)
      │                                       │
      ▼                                       ▼
 ┌──────────────────────────┐        ┌──────────────────┐
 │ ci-cd.yml                │        │ infra.yml        │
 │ test (Postgres container)│        │ Terraform        │
 │ → build/push (GHCR)      │        │ → Postgres free  │
 │ → deploy hook + /healthz │        └────────┬─────────┘
 └────────────┬─────────────┘                 │
              ▼                               ▼
        Render (Docker) ── AIVEN_DB_URL ──▶ Aiven PostgreSQL (SSL)
              ▲
              │ POST /api/refresh a cada 6h
        refresh-data.yml
```
