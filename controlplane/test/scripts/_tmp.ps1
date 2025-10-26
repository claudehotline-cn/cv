param(
  [string]$BaseUrl = "http://127.0.0.1:18080",
  [string]$CfgDir = "controlplane/config-notls"
)

$ErrorActionPreference = 'Stop'

function Wait-Http($url, [int]$TimeoutSec=12) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200) { return $true } } catch { }
    Start-Sleep -Milliseconds 250
  }
  return $false
}

function Wait-VAReady([string]$CpBase, [int]$TimeoutSec=12) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri ("{0}/api/system/info" -f $CpBase) -UseBasicParsing -TimeoutSec 2
      $j = $null; try { $j = $r.Content | ConvertFrom-Json } catch {}
      if ($j -and $j.data -and $j.data.runtime -and ($j.data.runtime.provider -ne $null) -and ($j.data.runtime.provider -ne "")) { return $true }
    } catch {}
    Start-Sleep -Milliseconds 300
  }
  return $false
}

try {
  # Ensure backends running
  pwsh -NoProfile -File 'tools/start_backends.ps1' | Write-Output

  # Start controlplane and capture stdout (audit)
  $cp = 'controlplane/build/bin/controlplane.exe'
  if (-not (Test-Path $cp)) { throw "controlplane.exe not found" }
  $log = Join-Path $env:TEMP ('cp_audit_'+[guid]::NewGuid().ToString()+'.log')
  $p = Start-Process -FilePath $cp -ArgumentList $CfgDir -PassThru -WindowStyle Hidden -RedirectStandardOutput $log
  if (-not (Wait-Http "$BaseUrl/metrics" 12)) { throw "controlplane not ready" }
  if (-not (Wait-VAReady $BaseUrl 12)) { Write-Host "[warn] VA not confirmed ready; continue negative test" -ForegroundColor Yellow }

  # Trigger VA apply failure by invalid spec
  $cid = (Get-Date).ToString('yyyyMMddHHmmssfff')
  $payload = '{"attach_id":"neg-'+$cid+'","source_uri":"rtsp://127.0.0.1:8554/camera_01","pipeline_name":"pneg-'+$cid+'","spec":{"yaml_path":"__no_such__.yaml"}}'
  $headers = @{ 'X-Correlation-Id' = $cid }
  $code = 0
  try {
    $r = Invoke-WebRequest -Uri "$BaseUrl/api/orch/attach_apply" -Method Post -ContentType 'application/json' -Body $payload -Headers $headers -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
    $code = $r.StatusCode
  } catch {
    try { $code = $_.Exception.Response.StatusCode.Value__ } catch { $code = 0 }
  }
  if ($code -eq 202) { Write-Output "FAIL: expected non-202, got 202"; exit 1 }

  # Evidence: audit log contains va_apply_failed for this corr id
  Start-Sleep -Milliseconds 500
  $txt = Get-Content -Raw -Path $log -ErrorAction SilentlyContinue
  if (-not $txt) { Write-Output 'FAIL: no audit output'; exit 1 }
  if ($txt -notmatch ('orch\.attach_apply\.va_apply_failed')) { Write-Output 'FAIL: expected audit for apply_failed'; exit 1 }
  Write-Output 'PASS'
  exit 0
} finally {
  try { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force } } catch { }
}


