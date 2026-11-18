#!/usr/bin/env bash
# Provisiona toda a infraestrutura do "CitizenTech no Ar".
# Uso:  GRUPO=g12 ALERT_EMAIL=voce@fiap.com.br bash infra/setup-azure.sh
# Pré-requisito: az login
set -euo pipefail

GRUPO="${GRUPO:?defina GRUPO (ex.: g12) - usado para nomes únicos}"
ALERT_EMAIL="${ALERT_EMAIL:?defina ALERT_EMAIL}"
RUNTIME="${RUNTIME:-PYTHON:3.12}"     # NODE:20-lts | DOTNETCORE:8.0 | JAVA:17-java17 ...
LOC="${LOC:-brazilsouth}"

RG="rg-citizentech"
PLAN="plan-citizentech"
APP="citizentech-${GRUPO}"
KV="kv-citizentech-${GRUPO}"
AI="ai-citizentech"
AG="ag-citizentech-equipe"

echo ">> Resource Group"
az group create -n "$RG" -l "$LOC" -o none

echo ">> App Service Plan (B1 Linux) + Web App"
az appservice plan create -n "$PLAN" -g "$RG" --sku B1 --is-linux -o none
az webapp create -n "$APP" -g "$RG" -p "$PLAN" --runtime "$RUNTIME" -o none

echo ">> Comando de inicialização (Python/gunicorn)"
az webapp config set -n "$APP" -g "$RG" --startup-file "gunicorn --bind=0.0.0.0 --timeout 600 app:app" -o none

echo ">> Hardening: HTTPS only, TLS 1.2, FTP desabilitado, health check"
az webapp update -n "$APP" -g "$RG" --https-only true -o none
az webapp config set -n "$APP" -g "$RG" --min-tls-version 1.2 --ftps-state Disabled \
  --generic-configurations '{"healthCheckPath":"/health"}' -o none

echo ">> Application Insights"
az extension add -n application-insights --only-show-errors || true
CONN=$(az monitor app-insights component create -a "$AI" -g "$RG" -l "$LOC" \
  --kind web --query connectionString -o tsv)

echo ">> Managed Identity + Key Vault (RBAC)"
PRINCIPAL=$(az webapp identity assign -n "$APP" -g "$RG" --query principalId -o tsv)
az keyvault create -n "$KV" -g "$RG" -l "$LOC" --enable-rbac-authorization true -o none
KV_ID=$(az keyvault show -n "$KV" -g "$RG" --query id -o tsv)
az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" -o none

# Seu usuário precisa poder criar segredos
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee-object-id "$ME" --assignee-principal-type User \
  --role "Key Vault Secrets Officer" --scope "$KV_ID" -o none
sleep 30   # propagação do RBAC

echo ">> Segredo de exemplo no Key Vault, referenciado pelo App Service"
az keyvault secret set --vault-name "$KV" -n API-KEY-EXTERNA --value "troque-este-valor" -o none
az webapp config appsettings set -n "$APP" -g "$RG" -o none --settings \
  APPLICATIONINSIGHTS_CONNECTION_STRING="$CONN" \
  API_KEY_EXTERNA="@Microsoft.KeyVault(VaultName=${KV};SecretName=API-KEY-EXTERNA)" \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true

echo ">> Action Group (e-mail) + alertas"
az monitor action-group create -n "$AG" -g "$RG" --short-name citizen \
  --action email equipe "$ALERT_EMAIL" -o none
APP_ID=$(az webapp show -n "$APP" -g "$RG" --query id -o tsv)
AG_ID=$(az monitor action-group show -n "$AG" -g "$RG" --query id -o tsv)

az monitor metrics alert create -n "alerta-http-5xx" -g "$RG" --scopes "$APP_ID" \
  --condition "total Http5xx > 3" --window-size 5m --evaluation-frequency 1m \
  --severity 2 --action "$AG_ID" --description "Mais de 3 erros 5xx em 5 min" -o none

az monitor metrics alert create -n "alerta-lentidao" -g "$RG" --scopes "$APP_ID" \
  --condition "avg HttpResponseTime > 3" --window-size 5m --evaluation-frequency 1m \
  --severity 3 --action "$AG_ID" --description "Tempo médio de resposta > 3s" -o none

az monitor metrics alert create -n "alerta-health-check" -g "$RG" --scopes "$APP_ID" \
  --condition "avg HealthCheckStatus < 100" --window-size 5m --evaluation-frequency 1m \
  --severity 1 --action "$AG_ID" --description "Health check falhando" -o none

echo ">> Publish profile (adicione como secret AZURE_PUBLISH_PROFILE no GitHub)"
az webapp deployment list-publishing-profiles -n "$APP" -g "$RG" --xml > publish-profile.xml
echo "   Salvo em publish-profile.xml  (NÃO commitar - já está no .gitignore)"

cat << MSG

PRONTO.
  URL do MVP : https://${APP}.azurewebsites.net
  Secrets GitHub: AZURE_APP_NAME=${APP}  |  AZURE_PUBLISH_PROFILE=<conteúdo de publish-profile.xml>
  Depois apague publish-profile.xml.
  Manual no portal: Availability test (Application Insights > Availability) apontando p/ /health
  RBAC dos colegas: az role assignment create --assignee <email> --role Contributor --resource-group ${RG}
MSG
