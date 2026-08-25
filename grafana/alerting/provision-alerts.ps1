param(
    [string]$GrafanaUrl = "http://localhost:3000",
    [string]$GrafanaUser = "admin",
    [string]$GrafanaPassword = "admin"
)

$ErrorActionPreference = "Stop"
$folderUid = "ai-production-alerts"
$folderTitle = "AI Production Alerts"
$groupName = "Render Farm Incidents"
$rulesPath = Join-Path $PSScriptRoot "rules.json"
$rules = Get-Content -LiteralPath $rulesPath -Raw | ConvertFrom-Json
$token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${GrafanaUser}:${GrafanaPassword}"))
$headers = @{ Authorization = "Basic $token"; "Content-Type" = "application/json" }

$folderExists = $true
try {
    Invoke-RestMethod -Headers $headers -Uri "$GrafanaUrl/api/folders/$folderUid" | Out-Null
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 404) {
        $folderExists = $false
    } else {
        throw
    }
}
if (-not $folderExists) {
    $folderBody = @{ uid = $folderUid; title = $folderTitle } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Headers $headers -Uri "$GrafanaUrl/api/folders" -Body $folderBody | Out-Null
}

$existingRules = Invoke-RestMethod -Headers $headers -Uri "$GrafanaUrl/api/v1/provisioning/alert-rules"
foreach ($definition in $rules) {
    $rule = @{
        title = $definition.title
        ruleGroup = $groupName
        folderUID = $folderUid
        noDataState = "OK"
        execErrState = "Error"
        for = $definition.for
        condition = "C"
        annotations = @{
            summary = $definition.summary
            description = $definition.description
            dashboard_url = "$GrafanaUrl/d/ai-production-director/ai-production-director"
            runbook_url = "http://localhost:8080/scenarios"
        }
        labels = @{
            severity = $definition.severity
            component = $definition.component
            service = "render-farm-simulator"
        }
        data = @(
            @{
                refId = "A"
                queryType = ""
                relativeTimeRange = @{ from = 300; to = 0 }
                datasourceUid = "prometheus"
                model = @{
                    editorMode = "code"
                    expr = $definition.expression
                    instant = $true
                    intervalMs = 1000
                    maxDataPoints = 43200
                    range = $false
                    refId = "A"
                }
            },
            @{
                refId = "B"
                queryType = ""
                relativeTimeRange = @{ from = 0; to = 0 }
                datasourceUid = "__expr__"
                model = @{ expression = "A"; reducer = "last"; settings = @{ mode = "dropNN" }; type = "reduce"; refId = "B" }
            },
            @{
                refId = "C"
                queryType = ""
                relativeTimeRange = @{ from = 0; to = 0 }
                datasourceUid = "__expr__"
                model = @{
                    expression = "B"
                    type = "threshold"
                    refId = "C"
                    conditions = @(@{
                        evaluator = @{ params = @(0); type = "gt" }
                        operator = @{ type = "and" }
                        query = @{ params = @("C") }
                        reducer = @{ params = @(); type = "last" }
                        type = "query"
                    })
                }
            }
        )
    }

    $body = $rule | ConvertTo-Json -Depth 30
    $existing = $existingRules.Where({ $_.title -eq $definition.title }, "First")
    if ($existing) {
        Invoke-RestMethod -Method Put -Headers $headers -Uri "$GrafanaUrl/api/v1/provisioning/alert-rules/$($existing.uid)" -Body $body | Out-Null
        Write-Host "Updated: $($definition.title)"
    } else {
        Invoke-RestMethod -Method Post -Headers $headers -Uri "$GrafanaUrl/api/v1/provisioning/alert-rules" -Body $body | Out-Null
        Write-Host "Created: $($definition.title)"
    }
}

$encodedGroup = [Uri]::EscapeDataString($groupName)
$groupUri = "$GrafanaUrl/api/v1/provisioning/folder/$folderUid/rule-groups/$encodedGroup"
$group = Invoke-RestMethod -Headers $headers -Uri $groupUri
if ($group.interval -ne 10) {
    $group.interval = 10
    $groupBody = $group | ConvertTo-Json -Depth 50
    Invoke-RestMethod -Method Put -Headers $headers -Uri $groupUri -Body $groupBody | Out-Null
}
Write-Host "Evaluation interval: 10s"
