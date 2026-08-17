param(
    [string]$ImageTag = "latest"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path .env) {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
        $k, $v = $_.Split('=', 2)
        [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim().Trim('"'), "Process")
    }
}

$sub = $env:AZURE_SUBSCRIPTION_ID
$rg = $env:AZURE_RESOURCE_GROUP
$acr = $env:AZURE_ACR_NAME
$ws = if ($env:AZURE_ML_WORKSPACE_NAME) { $env:AZURE_ML_WORKSPACE_NAME } else { $env:AZURE_AI_FOUNDRY_PROJECT_NAME }
$endpoint = if ($env:ENDPOINT_NAME) { $env:ENDPOINT_NAME } else { "hebrew-loan-agent" }
$deployName = if ($env:DEPLOYMENT_NAME) { $env:DEPLOYMENT_NAME } else { "blue" }

if (-not $sub -or -not $rg -or -not $acr -or -not $ws) {
    throw "Set AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_ACR_NAME, AZURE_ML_WORKSPACE_NAME (or AZURE_AI_FOUNDRY_PROJECT_NAME)"
}

Write-Host "==> Checking Azure CLI login"
az account show | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Run: az login" }
az account set --subscription $sub
az group show -n $rg | Out-Null

Write-Host "==> ACR build"
$acrServer = az acr show -n $acr --query loginServer -o tsv
az acr build --registry $acr --image "hebrew-loan-agent:$ImageTag" --file Dockerfile .

$fullImage = "$acrServer/hebrew-loan-agent:$ImageTag"
$tmp = New-TemporaryFile
(Get-Content deployment.yaml -Raw) `
    -replace '\$\{AZURE_ACR_LOGIN_SERVER\}', $acrServer `
    -replace 'name: blue', "name: $deployName" `
    -replace 'endpoint_name: hebrew-loan-agent', "endpoint_name: $endpoint" |
    Set-Content -Path $tmp -Encoding utf8

Write-Host "==> Endpoint"
$exists = az ml online-endpoint show --name $endpoint -g $rg -w $ws 2>$null
if ($exists) {
    az ml online-endpoint update --file endpoint.yaml -g $rg -w $ws --set name=$endpoint
} else {
    az ml online-endpoint create --file endpoint.yaml -g $rg -w $ws --set name=$endpoint
}

Write-Host "==> Deployment"
$set = @("--set", "environment.image=$fullImage")
if ($env:FOUNDRY_PROJECT_ENDPOINT) {
    $set += @("--set", "environment_variables.FOUNDRY_PROJECT_ENDPOINT=$($env:FOUNDRY_PROJECT_ENDPOINT)")
}
if ($env:AZURE_AI_MODEL_DEPLOYMENT_NAME) {
    $set += @("--set", "environment_variables.AZURE_AI_MODEL_DEPLOYMENT_NAME=$($env:AZURE_AI_MODEL_DEPLOYMENT_NAME)")
}
$depExists = az ml online-deployment show --name $deployName --endpoint-name $endpoint -g $rg -w $ws 2>$null
if ($depExists) {
    az ml online-deployment update --file $tmp -g $rg -w $ws @set
} else {
    az ml online-deployment create --file $tmp -g $rg -w $ws @set
}

az ml online-endpoint update --name $endpoint -g $rg -w $ws --traffic "$deployName=100"

Write-Host "==> Smoke test (Hebrew)"
az ml online-endpoint invoke --name $endpoint -g $rg -w $ws --request-file sample_hebrew_request.json
az ml online-endpoint show --name $endpoint -g $rg -w $ws --query scoring_uri -o tsv
Remove-Item $tmp -ErrorAction SilentlyContinue
