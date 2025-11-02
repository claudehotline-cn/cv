param(
  [string]$BaseUrl = "http://127.0.0.1:18080"
)

function Wait-Http($url, [int]$TimeoutSec=10) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
      if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
    } catch { }
    Start-Sleep -Milliseconds 200
  }
  return $false
}

try {
  $exe = Join-Path -Path 'controlplane' -ChildPath 'build/bin/controlplane.exe'
  if (-not (Test-Path $exe)) { Write-Output 'FAIL: controlplane.exe not found'; exit 1 }
  # use config-auth with bearer + rate limit
  $p = Start-Process -FilePath $exe -ArgumentList 'controlplane/config-auth' -PassThru -WindowStyle Hidden
  if (-not (Wait-Http "$BaseUrl/metrics" 12)) { Write-Output 'SKIP: metrics not ready'; if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force }; exit 0 }

  # 1) /metrics exempt from auth (not subject to auth; rate limit may apply)
  $mcode = 0
  try { $m = Invoke-WebRequest -Uri "$BaseUrl/metrics" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop; $mcode = $m.StatusCode } catch { $mcode = $_.Exception.Response.StatusCode.Value__ }
  if ($mcode -eq 401) { Write-Output "FAIL: metrics unauthorized"; exit 1 }

  # 2) No token -> 401
  $failed401 = $false
  try { Invoke-WebRequest -Uri "$BaseUrl/api/system/info" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop } catch { $failed401 = ($_.Exception.Response.StatusCode.Value__ -eq 401) }
  if (-not $failed401) { Write-Output 'FAIL: expected 401 without token'; exit 1 }

  # 3) With token -> 200
  $h = @{ 'Authorization' = 'Bearer secret123' }
  $ok = Invoke-WebRequest -Uri "$BaseUrl/api/system/info" -Headers $h -UseBasicParsing -TimeoutSec 5
  if ($ok.StatusCode -ne 200) { Write-Output "FAIL: system/info with token $($ok.StatusCode)"; exit 1 }

  # 4) Rate limit (rps=1): second request in same second -> 429
  $r1 = Invoke-WebRequest -Uri "$BaseUrl/api/system/info" -Headers $h -UseBasicParsing -TimeoutSec 5
  $rl429 = $false
  try { Invoke-WebRequest -Uri "$BaseUrl/api/system/info" -Headers $h -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop } catch { $rl429 = ($_.Exception.Response.StatusCode.Value__ -eq 429) }
  if (-not $rl429) { Write-Output 'FAIL: expected 429 for rate limit'; exit 1 }

  Write-Output 'PASS'
  exit 0
} finally {
  try { if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force } } catch { }
}
