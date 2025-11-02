Param(
  [string]$CpBase = "http://127.0.0.1:8080",
  [string]$Pipeline = "p_demo"
)
$ErrorActionPreference = 'Stop'

function Assert-Status($resp, [int]$code) {
  if ($resp.StatusCode -ne $code) {
    Write-Error "EXPECT $code, GOT $($resp.StatusCode): $($resp.Content)"
  }
}

# Ensure CP is running
try { $null = iwr -UseBasicParsing "$CpBase/api/system/info" -TimeoutSec 5 } catch {
  & "$PSScriptRoot/../../../tools/start_cp.ps1" | Out-Null
  Start-Sleep -Seconds 1
}

# Locate YAML
$yaml = Join-Path (Resolve-Path "$PSScriptRoot/../../build-ninja/bin/config/graphs").Path "analyzer_multistage_example.yaml"
if (!(Test-Path $yaml)) { Write-Error "YAML not found: $yaml" }

# Apply
$body = @{ pipeline_name = $Pipeline; spec = @{ yaml_path = $yaml } } | ConvertTo-Json -Compress
$apply = iwr -UseBasicParsing "$CpBase/api/control/apply_pipeline" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 15 -SkipHttpErrorCheck:$true
Assert-Status $apply 202

# Status
$st = iwr -UseBasicParsing "$CpBase/api/control/status?pipeline_name=$Pipeline" -TimeoutSec 10 -SkipHttpErrorCheck:$true
Assert-Status $st 200

# Drain
$dr = iwr -UseBasicParsing "$CpBase/api/control/drain" -Method Post -Body (@{ pipeline_name=$Pipeline; timeout_sec=2 } | ConvertTo-Json -Compress) -ContentType 'application/json' -TimeoutSec 15 -SkipHttpErrorCheck:$true
Assert-Status $dr 202

# Delete
$del = iwr -UseBasicParsing "$CpBase/api/control/pipeline?pipeline_name=$Pipeline" -Method Delete -TimeoutSec 10 -SkipHttpErrorCheck:$true
Assert-Status $del 202

Write-Host "[cp_control_smoke] PASS" -ForegroundColor Green
