param(
    [string]$GrafanaUrl = "http://localhost:3000",
    [string]$GrafanaUser = "admin",
    [string]$GrafanaPassword = "admin"
)

$ErrorActionPreference = "Stop"
$contactName = "AI Production Incident Webhook"
$token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${GrafanaUser}:${GrafanaPassword}"))
$headers = @{ Authorization = "Basic $token"; "Content-Type" = "application/json" }
$existing = Invoke-RestMethod -Headers $headers -Uri "$GrafanaUrl/api/v1/provisioning/contact-points"
$contact = $existing.Where({ $_.name -eq $contactName }, "First")
$body = @{
    name = $contactName
    type = "webhook"
    settings = @{
        url = "http://render-simulator:8080/webhooks/grafana"
        httpMethod = "POST"
    }
    disableResolveMessage = $false
} | ConvertTo-Json -Depth 10

if ($contact) {
    Invoke-RestMethod -Method Put -Headers $headers -Uri "$GrafanaUrl/api/v1/provisioning/contact-points/$($contact.uid)" -Body $body | Out-Null
    Write-Host "Updated contact point: $contactName"
} else {
    Invoke-RestMethod -Method Post -Headers $headers -Uri "$GrafanaUrl/api/v1/provisioning/contact-points" -Body $body | Out-Null
    Write-Host "Created contact point: $contactName"
}

$policy = @{
    receiver = $contactName
    group_by = @("grafana_folder", "alertname")
    group_wait = "2s"
    group_interval = "10s"
    repeat_interval = "4h"
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method Put -Headers $headers -Uri "$GrafanaUrl/api/v1/provisioning/policies" -Body $policy | Out-Null
Write-Host "Grafana alerts now route to the incident webhook."
