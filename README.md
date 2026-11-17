# CidadeViva — MVP

Global Solution FIAP 2026.2 · CitizenTech · Engenharia de Software 4º ano · Grupo CitizenTech
Giovanna Franco Gaudino Rodrigues (RM553701) · Rafael de Almeida Sigoli (RM554019) · Rafael Jorge Del Padre (RM552765)

**O cidadão reporta um problema urbano, a IA sugere o tipo, uma pessoa confere quando há dúvida, e o robô registra no portal legado da prefeitura e devolve o protocolo.**

## Ficha Técnica do MVP

| Campo | CidadeViva |
|---|---|
| Nome do produto | CidadeViva |
| Cidadão e território | Moradores de cidades brasileiras que veem buracos, bueiros entupidos, calçadas quebradas e lixo. Cliente pagante: a prefeitura. Dados reais de São Paulo (SP156). |
| Problema | O cidadão reporta e não recebe resposta, e a prefeitura redigita cada reclamação em portais legados sem API. |
| Proposta de valor | Reporte em 3 passos, com endereço lido da conta de luz/água/telefone, código de acompanhamento e protocolo da prefeitura. |
| Arquitetura | Este app (Starlette) + Visão (OCR) + triagem por IA + ponte RPA (UiPath) + pipeline de dados (Airflow) + Azure App Service. |
| Fontes de dados | SP156 (real, CC0) · reportes do app · faturas sintéticas (teste de Visão). |
| Modelos de IA | Tesseract + OpenCV (Visão) · LLM via OpenRouter com *fallback* para regras lexicais (triagem). |
| URL do MVP | _preencher após o deploy_ |
| Repositórios | [Big Data](https://github.com/giovannafgaudino/GS_CitizenTech_BigData) · [Visão](https://github.com/delpadre/CidadeViva-ComputerVision) · este |
| Indicadores de impacto | Tempo até o protocolo · % de reportes com protocolo · horas de digitação evitadas · % de revisão humana · resolução por subprefeitura. |
| ODS | 11, 9, 10 (e 16) |

## Como funciona

```
Cidadão ──► /  (3 passos)  ──► POST /extract-address   (Visão: foto da conta → endereço, opcional)
                           ──► POST /api/triagem       (IA: sugere categoria; nunca bloqueia o reporte)
                           ──► POST /api/reportes      (grava; confiança < 0,70 => status "novo", exige revisão)
Atendente ► /admin ► aprova os "novos" ► status "triado"
Robô UiPath ◄ GET /rpa/fila.csv   (reclamacoes.csv)   ► portal da prefeitura
            ► POST /rpa/resultado (reclamacoes_resultado.csv: status + protocolo) ► "enviado_prefeitura"
Pipeline Airflow ◄ GET /reportes/export?desde=&ate=   (contrato do ingest.py do repositório de Big Data)
Painel /painel ◄ /api/stats (app) + /api/demanda (DW do pipeline, via DW_PATH)
```

Status: `novo → triado → enviado_prefeitura → resolvido` (mesmos nomes do pipeline de dados).

## Rodar localmente

```bash
sudo apt install tesseract-ocr tesseract-ocr-por      # ou brew install tesseract tesseract-lang
pip install -r requirements-dev.txt
cp .env.example .env   # defina ADMIN_KEY
export $(grep -v '^#' .env | xargs)
python -m pytest -q tests                             # 14 testes
uvicorn app.main:app --reload                         # http://localhost:8000
```

Ou com Docker: `docker build -t cidadeviva . && docker run -p 8000:8000 -e ADMIN_KEY=troque cidadeviva`.

## Deploy no Azure (App Service + GitHub Actions)

1. Azure Portal: crie um **Resource Group** e um **App Service** *Publish: Container*, SO Linux, plano B1 (ou F1 se disponível), e anote o nome.
2. App Service > **Configuration**: `WEBSITES_PORT=8000`, `WEBSITES_ENABLE_APP_SERVICE_STORAGE=true` (mantém `/home/data`), `ADMIN_KEY=<chave longa>`, opcional `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`. Em **Settings > Configuration > General** ative **HTTPS Only**.
3. Em **Application Insights**, crie/vincule um recurso e copie a *connection string* para `APPLICATIONINSIGHTS_CONNECTION_STRING`. Crie um **alerta** (por exemplo, falhas HTTP 5xx > 0 em 5 min) com envio de e-mail.
4. App Service > **Overview > Get publish profile**; no GitHub: *Settings > Secrets > Actions* crie `AZURE_WEBAPP_PUBLISH_PROFILE` (conteúdo do arquivo) e, em *Variables*, `AZURE_WEBAPP_NAME`.
5. Faça push na `main`: o workflow roda os testes, constrói a imagem, publica em `ghcr.io/<usuario>/cidadeviva-mvp` e faz o deploy. Depois do primeiro push, deixe o pacote **público** (GitHub > Packages > Package settings) para o App Service conseguir baixar a imagem. Configure no App Service a imagem `ghcr.io/<usuario>/cidadeviva-mvp:latest`.
6. Confira `https://<app>.azurewebsites.net/health`.

## Ligações com as outras entregas

**Big Data.** No repositório de Big Data, faça `ingerir_cidadeviva` enviar a chave do app (3 linhas em `pipeline/ingest.py`):

```python
req = urllib.request.Request(url, headers={"X-API-Key": os.getenv("CIDADEVIVA_API_KEY", "")})
with urllib.request.urlopen(req, timeout=60) as r:
    reportes = json.loads(r.read().decode("utf-8"))
```

e defina `CIDADEVIVA_API_URL=https://<app>.azurewebsites.net` e `CIDADEVIVA_API_KEY=<ADMIN_KEY>`. Para o painel de demanda, copie o `cidadeviva_dw.sqlite` gerado pelo `run_local.py` para `/home/data/` e defina `DW_PATH=/home/data/cidadeviva_dw.sqlite`.

**RPA.** O robô lê `data\reclamacoes.csv` e grava `data\reclamacoes_resultado.csv`. Em `/admin`: *Baixar reclamacoes.csv* → colocar na pasta `data` do robô → rodar → *Enviar reclamacoes_resultado.csv*. O protocolo aparece na tela do cidadão. Em produção o robô chamaria essas duas rotas direto, com a `ADMIN_KEY` num Credential Asset do Orchestrator.

**Generative AI.** `app/triagem.py` chama o OpenRouter. Se a entrega de GenAI do grupo definir outro prompt ou modelo, troque `_prompt()` e `OPENROUTER_MODEL`; o restante do app não muda.

## Segurança e LGPD

- Segredos só em variáveis de ambiente; rotas de atendente/robô/pipeline exigem `ADMIN_KEY` (falham fechadas se ela não existir).
- Não coletamos nome nem e-mail: o usuário é um identificador aleatório do navegador.
- Fotos são decodificadas e regravadas (remove EXIF, inclusive GPS escondido), com limite de 8 MB; a foto da conta nunca é guardada.
- PII (CPF, telefone, e-mail) é mascarada antes de qualquer texto sair para o LLM.
- Cabeçalhos de segurança, limite de requisições por IP, logs sem corpo e sem IP.
- IA responsável: a descrição é tratada como dado (defesa contra injeção de prompt), a saída é validada contra a lista fixa de categorias, e confiança < 0,70 exige conferência humana antes do envio.

## O que é real e o que é simulado

- **Real:** leitura de endereço por OCR, triagem, banco, fila e ciclo de status, contrato de exportação para o pipeline, SP156.
- **Simulado:** o portal da prefeitura (página HTML do robô), as faturas de teste (sintéticas) e a execução do robô, que roda no computador do grupo, não no Azure.
- **Limites conhecidos:** SQLite num único contêiner (não escala horizontalmente); limite de requisições em memória; a subprefeitura só é calculada para a cidade de São Paulo e por centroides aproximados; o login do atendente é uma chave única, não contas individuais.
