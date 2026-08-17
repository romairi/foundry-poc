#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID}"
: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"
: "${AZURE_ACR_NAME:?Set AZURE_ACR_NAME}"
: "${AZURE_ML_WORKSPACE_NAME:=${AZURE_AI_FOUNDRY_PROJECT_NAME:?Set AZURE_ML_WORKSPACE_NAME or AZURE_AI_FOUNDRY_PROJECT_NAME}}"
: "${ENDPOINT_NAME:=hebrew-loan-agent}"
: "${DEPLOYMENT_NAME:=blue}"
: "${AZURE_LOCATION:=swedencentral}"

IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="hebrew-loan-agent"

echo "==> Checking Azure CLI login"
az account show >/dev/null || { echo "Run: az login"; exit 1; }
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az group show -n "$AZURE_RESOURCE_GROUP" >/dev/null

echo "==> ACR login + build"
az acr show -n "$AZURE_ACR_NAME" -g "$AZURE_RESOURCE_GROUP" >/dev/null
ACR_SERVER="$(az acr show -n "$AZURE_ACR_NAME" --query loginServer -o tsv)"
az acr build \
  --registry "$AZURE_ACR_NAME" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  --file Dockerfile \
  .

FULL_IMAGE="${ACR_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
echo "==> Image: ${FULL_IMAGE}"

TMP_DEPLOY="$(mktemp)"
sed "s|\${AZURE_ACR_LOGIN_SERVER}|${ACR_SERVER}|g; s|name: blue|name: ${DEPLOYMENT_NAME}|g; s|endpoint_name: hebrew-loan-agent|endpoint_name: ${ENDPOINT_NAME}|g" \
  deployment.yaml > "$TMP_DEPLOY"

echo "==> Endpoint create/update"
if az ml online-endpoint show --name "$ENDPOINT_NAME" -g "$AZURE_RESOURCE_GROUP" -w "$AZURE_ML_WORKSPACE_NAME" >/dev/null 2>&1; then
  az ml online-endpoint update --file endpoint.yaml -g "$AZURE_RESOURCE_GROUP" -w "$AZURE_ML_WORKSPACE_NAME" --set name="$ENDPOINT_NAME"
else
  az ml online-endpoint create --file endpoint.yaml -g "$AZURE_RESOURCE_GROUP" -w "$AZURE_ML_WORKSPACE_NAME" --set name="$ENDPOINT_NAME"
fi

echo "==> Deployment create/update"
SET_ARGS=(--set environment.image="$FULL_IMAGE")
if [[ -n "${FOUNDRY_PROJECT_ENDPOINT:-}" ]]; then
  SET_ARGS+=(--set "environment_variables.FOUNDRY_PROJECT_ENDPOINT=$FOUNDRY_PROJECT_ENDPOINT")
fi
if [[ -n "${AZURE_AI_MODEL_DEPLOYMENT_NAME:-}" ]]; then
  SET_ARGS+=(--set "environment_variables.AZURE_AI_MODEL_DEPLOYMENT_NAME=$AZURE_AI_MODEL_DEPLOYMENT_NAME")
fi
if az ml online-deployment show --name "$DEPLOYMENT_NAME" --endpoint-name "$ENDPOINT_NAME" -g "$AZURE_RESOURCE_GROUP" -w "$AZURE_ML_WORKSPACE_NAME" >/dev/null 2>&1; then
  az ml online-deployment update --file "$TMP_DEPLOY" -g "$AZURE_RESOURCE_GROUP" -w "$AZURE_ML_WORKSPACE_NAME" "${SET_ARGS[@]}"
else
  az ml online-deployment create --file "$TMP_DEPLOY" -g "$AZURE_RESOURCE_GROUP" -w "$AZURE_ML_WORKSPACE_NAME" "${SET_ARGS[@]}"
fi

echo "==> Route 100% traffic to ${DEPLOYMENT_NAME}"
az ml online-endpoint update \
  --name "$ENDPOINT_NAME" \
  -g "$AZURE_RESOURCE_GROUP" \
  -w "$AZURE_ML_WORKSPACE_NAME" \
  --traffic "${DEPLOYMENT_NAME}=100"

echo "==> Smoke test (Hebrew payload)"
az ml online-endpoint invoke \
  --name "$ENDPOINT_NAME" \
  -g "$AZURE_RESOURCE_GROUP" \
  -w "$AZURE_ML_WORKSPACE_NAME" \
  --request-file sample_hebrew_request.json

echo "Done. Scoring URI:"
az ml online-endpoint show --name "$ENDPOINT_NAME" -g "$AZURE_RESOURCE_GROUP" -w "$AZURE_ML_WORKSPACE_NAME" --query scoring_uri -o tsv
rm -f "$TMP_DEPLOY"
