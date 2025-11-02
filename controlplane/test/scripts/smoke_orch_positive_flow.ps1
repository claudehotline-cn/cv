param(
  [string]$BaseUrl = "http://127.0.0.1:18080",
  [string]$CfgDir = "controlplane/config"
)

$ErrorActionPreference = 'Stop'

function Wait-Http($url, [int]$TimeoutSec=15) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200) { return $true } } catch { }
    Start-Sleep -Milliseconds 250
  }
  return $false
}

try {
  # Ensure backends running (enable TLS if using TLS config)
  $useTls = ($CfgDir -like '*controlplane/config*' -and $CfgDir -notlike '*config-notls*')
  if ($useTls) {
    $env:VSM_TLS_ENABLED='1'; $env:VSM_TLS_CA='controlplane/config/certs/ca.pem'; $env:VSM_TLS_CERT='controlplane/config/certs/vsm_server.crt'; $env:VSM_TLS_KEY='controlplane/config/certs/vsm_server.key'
    $env:VA_TLS_ENABLED='1';  $env:VA_TLS_CA='controlplane/config/certs/ca.pem';  $env:VA_TLS_CERT='controlplane/config/certs/va_server.crt';  $env:VA_TLS_KEY='controlplane/config/certs/va_server.key'
  }
  pwsh -NoProfile -File 'tools/start_backends.ps1' | Write-Output

  # Start CP (notls) and wait
  $cp = 'controlplane/build/bin/controlplane.exe'
  if (-not (Test-Path $cp)) { throw "controlplane.exe not found" }
  $p = Start-Process -FilePath $cp -ArgumentList $CfgDir -PassThru -WindowStyle Hidden
  if (-not (Wait-Http ("{0}/metrics" -f $BaseUrl) 15)) { throw "controlplane not ready" }

  # Wait VA ready via system/info provider field
  $vaReady=$false
  for($i=0;$i -lt 20;$i++){
    try { $r = Invoke-WebRequest -Uri ("{0}/api/system/info" -f $BaseUrl) -UseBasicParsing -TimeoutSec 2; $j=$r.Content | ConvertFrom-Json; if ($j.data.runtime.provider) { $vaReady=$true; break } } catch {}
    Start-Sleep -Milliseconds 500
  }
  if (-not $vaReady) { Write-Host "[orch_pos] WARN: VA runtime not confirmed; continue" -ForegroundColor Yellow }

  # Resolve YAML
  $yaml = ''
  try { $yaml = Join-Path (Resolve-Path 'video-analyzer/build-ninja/bin/config/graphs').Path 'analyzer_multistage_example.yaml' } catch {}
  if (-not (Test-Path $yaml)) { Write-Host "[orch_pos] SKIP: yaml not found" -ForegroundColor Yellow; Stop-Process -Id $p.Id -Force; exit 0 }

  $cid = (Get-Date).ToString('yyyyMMddHHmmssfff')
  $pipe = 'p_orch_' + $cid
  $hdr = @{ 'X-Correlation-Id' = $cid; 'Content-Type'='application/json' }

  # Apply pipeline
  $apply = @{ pipeline_name = $pipe; spec = @{ yaml_path = $yaml } } | ConvertTo-Json -Compress
  $r1 = Invoke-WebRequest -Uri ("{0}/api/control/apply_pipeline" -f $BaseUrl) -Method Post -Headers $hdr -Body $apply -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
  if ($r1.StatusCode -ne 202) { throw "apply expect 202, got $($r1.StatusCode)" }

  # Wait a moment for VA to settle
  Start-Sleep -Seconds 1

  # Status
  $st = Invoke-WebRequest -Uri ("{0}/api/control/status?pipeline_name={1}" -f $BaseUrl,$pipe) -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
  if ($st.StatusCode -ne 200) { throw "status expect 200, got $($st.StatusCode)" }

  # Drain
  $dr = @{ pipeline_name=$pipe; timeout_sec=2 } | ConvertTo-Json -Compress
  $r3 = Invoke-WebRequest -Uri ("{0}/api/control/drain" -f $BaseUrl) -Method Post -Headers $hdr -Body $dr -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
  if ($r3.StatusCode -ne 202) { throw "drain expect 202, got $($r3.StatusCode)" }

  # Delete
  $r4 = Invoke-WebRequest -Uri ("{0}/api/control/pipeline?pipeline_name={1}" -f $BaseUrl,$pipe) -Method Delete -Headers $hdr -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
  if ($r4.StatusCode -ne 202) { throw "delete expect 202, got $($r4.StatusCode)" }

  Write-Host "[orch_positive_flow] PASS" -ForegroundColor Green
  Stop-Process -Id $p.Id -Force
  exit 0
} catch {
  Write-Host ("[orch_positive_flow] FAIL -> {0}" -f $_.Exception.Message) -ForegroundColor Red
  try { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force } } catch { }
  exit 1
}
