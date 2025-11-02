Param(
  [string]$CpBase = "http://127.0.0.1:8080",
  [string]$Pipeline = "p_demo",
  [string]$Node = "det",
  [string]$ModelUri = "D:/Projects/ai/cv/video-analyzer/build-ninja/bin/model/yolov12m.onnx"
)
$ErrorActionPreference = 'Stop'

function Assert-Status($resp, [int]$code) {
  if ($resp.StatusCode -ne $code) {
    Write-Error "EXPECT $code, GOT $($resp.StatusCode): $($resp.Content)"
  }
}

if (!(Test-Path $ModelUri)) {
  Write-Host "[cp_control_hotswap] SKIP: model not found: $ModelUri" -ForegroundColor Yellow
  exit 0
}

try { $null = iwr -UseBasicParsing "$CpBase/api/system/info" -TimeoutSec 5 } catch {
  & "$PSScriptRoot/../../../tools/start_cp.ps1" | Out-Null
  Start-Sleep -Seconds 1
}

# Ensure pipeline exists
$yaml = Join-Path (Resolve-Path "$PSScriptRoot/../../build-ninja/bin/config/graphs").Path "analyzer_multistage_example.yaml"
$applyBody = @{ pipeline_name = $Pipeline; spec = @{ yaml_path = $yaml } } | ConvertTo-Json -Compress
$apply = iwr -UseBasicParsing "$CpBase/api/control/apply_pipeline" -Method Post -Body $applyBody -ContentType 'application/json' -TimeoutSec 15 -SkipHttpErrorCheck:$true
if ($apply.StatusCode -ne 202 -and $apply.StatusCode -ne 409) {
  Write-Error "apply_pipeline failed: $($apply.StatusCode) $($apply.Content)"
}

# Hotswap
$hpBody = @{ pipeline_name=$Pipeline; node=$Node; model_uri=$ModelUri } | ConvertTo-Json -Compress
$hp = iwr -UseBasicParsing "$CpBase/api/control/hotswap" -Method Post -Body $hpBody -ContentType 'application/json' -TimeoutSec 60 -SkipHttpErrorCheck:$true
Assert-Status $hp 202

# Status
$st = iwr -UseBasicParsing "$CpBase/api/control/status?pipeline_name=$Pipeline" -TimeoutSec 10 -SkipHttpErrorCheck:$true
Assert-Status $st 200

Write-Host "[cp_control_hotswap] PASS" -ForegroundColor Green
