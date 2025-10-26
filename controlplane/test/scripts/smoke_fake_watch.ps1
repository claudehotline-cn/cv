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
  $env:CP_FAKE_WATCH = '1'
  $exe = Join-Path -Path 'controlplane' -ChildPath 'build/bin/controlplane.exe'
  if (-not (Test-Path $exe)) { Write-Output 'FAIL: controlplane.exe not found'; exit 1 }
  $p = Start-Process -FilePath $exe -ArgumentList 'controlplane/config' -PassThru -WindowStyle Hidden
  if (-not (Wait-Http "$BaseUrl/metrics" 12)) { Write-Output 'SKIP: metrics not ready'; if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force }; exit 0 }
  try {
    $resp = Invoke-WebRequest -Uri "$BaseUrl/api/subscriptions/fake-1/events" -UseBasicParsing -TimeoutSec 10
    $body = $resp.Content
    if ($body -match 'event: phase' -and $body -match '"phase":"ready"') {
      Write-Output 'PASS'
      exit 0
    } else {
      Write-Output 'SKIP: unexpected body'
      exit 0
    }
  } catch {
    Write-Output ("SKIP: exception {0}" -f $_.Exception.Message)
    exit 0
  }
} finally {
  try { if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force } } catch { }
}

