#!/usr/bin/env bash
# One-time setup, run by a person with Owner rights on the subscription, after `az login`.
# Creates the storage account that holds the Terraform state and a GitHub identity (OIDC, no secrets)
# that the deploy job uses. Prints the values to store as GitHub secrets and variables.
# Needs `gh` logged in: the OIDC subject prefix is read from the repository (it may contain numeric ids).
#
# Usage: SUBSCRIPTION_ID=<id> GITHUB_REPO=robbertpopa/ppc-smarthack infra/azure/bootstrap.sh
set -euo pipefail

: "${SUBSCRIPTION_ID:?set SUBSCRIPTION_ID}"
: "${GITHUB_REPO:?set GITHUB_REPO, for example owner/repo}"
LOCATION="${LOCATION:-germanywestcentral}"
STATE_RG="${STATE_RG:-rg-ppcsmart-tfstate}"
STATE_SA="${STATE_SA:-stppcsmarttf$(printf '%05d' $((RANDOM % 100000)))}"
STATE_CONTAINER="${STATE_CONTAINER:-tfstate}"
APP_NAME="${APP_NAME:-ppc-smarthack-github}"
SUB_PREFIX="${SUB_PREFIX:-$(gh api "repos/${GITHUB_REPO}/actions/oidc/customization/sub" --jq .sub_claim_prefix)}"

az account set --subscription "$SUBSCRIPTION_ID"
TENANT_ID="$(az account show --query tenantId -o tsv)"
ME="$(az ad signed-in-user show --query id -o tsv)"

az group create --name "$STATE_RG" --location "$LOCATION" >/dev/null
az storage account create \
  --name "$STATE_SA" --resource-group "$STATE_RG" --location "$LOCATION" \
  --sku Standard_LRS --min-tls-version TLS1_2 --allow-blob-public-access false >/dev/null
STATE_SA_ID="$(az storage account show --name "$STATE_SA" --resource-group "$STATE_RG" --query id -o tsv)"

az role assignment create --assignee "$ME" --role "Storage Blob Data Contributor" \
  --scope "$STATE_SA_ID" >/dev/null
echo "Waiting for the role assignment to propagate..."
sleep 30
az storage container create --name "$STATE_CONTAINER" --account-name "$STATE_SA" \
  --auth-mode login >/dev/null

APP_ID="$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)"
az ad sp create --id "$APP_ID" >/dev/null
SP_ID="$(az ad sp show --id "$APP_ID" --query id -o tsv)"

az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"github-main\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"${SUB_PREFIX}:ref:refs/heads/main\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}" >/dev/null
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"github-pull-request\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"${SUB_PREFIX}:pull_request\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}" >/dev/null

SCOPE="/subscriptions/${SUBSCRIPTION_ID}"
for ROLE in "Contributor" "User Access Administrator"; do
  az role assignment create --assignee-object-id "$SP_ID" --assignee-principal-type ServicePrincipal \
    --role "$ROLE" --scope "$SCOPE" >/dev/null
done
az role assignment create --assignee-object-id "$SP_ID" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$STATE_SA_ID" >/dev/null

cat <<EOF

Done. In the GitHub repository settings add:

  Secrets:   AZURE_CLIENT_ID=${APP_ID}
             AZURE_TENANT_ID=${TENANT_ID}
             AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}
             DEMO_TOKEN=<a token of your choice, optional>
  Variables: DEPLOY_ENABLED=true
             TFSTATE_RG=${STATE_RG}
             TFSTATE_SA=${STATE_SA}
             TFSTATE_CONTAINER=${STATE_CONTAINER}

For local Terraform, create infra/terraform/backend.hcl (git-ignored) with:

  resource_group_name  = "${STATE_RG}"
  storage_account_name = "${STATE_SA}"
  container_name       = "${STATE_CONTAINER}"
  key                  = "ppc-smarthack.tfstate"
  use_azuread_auth     = true

The identity has Contributor and User Access Administrator on the whole subscription so that
Terraform can create role assignments. Narrow it to a resource group if your policy requires it.
EOF
