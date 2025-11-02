param(
  [string]$BaseUrl = "http://127.0.0.1:18080",
  [int]$N = 6
)

function Wait-Http($url, [int]$TimeoutSec=10) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200) { return $true } } catch { }
    Start-Sleep -Milliseconds 200
  }
  return $false
}

function Get-MetricValue([string]$Text, [string]$Name) {
  foreach ($ln in ($Text -split "`n")) { if ($ln -like "$Name *") { $parts = $ln.Trim().Split(' '); if ($parts.Count -ge 2) { return [int64]$parts[-1] } } }
  return 0
}

try {
  $env:CP_FAKE_WATCH = '1'
  $exe = Join-Path -Path 'controlplane' -ChildPath 'build/bin/controlplane.exe'
  if (-not (Test-Path $exe)) { Write-Output 'FAIL: controlplane.exe not found'; exit 1 }
  $p = Start-Process -FilePath $exe -ArgumentList 'controlplane/config' -PassThru -WindowStyle Hidden
  if (-not (Wait-Http "$BaseUrl/metrics" 12)) { Write-Output 'SKIP: metrics not ready'; if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force }; exit 0 }

  $m0 = Invoke-WebRequest -Uri "$BaseUrl/metrics" -UseBasicParsing -TimeoutSec 5
  $r0 = Get-MetricValue $m0.Content 'cp_sse_reconnects'

  $jobs = @()
  for ($i=0; $i -lt $N; $i++) {
    $id = "fake-$i"
    $jobs += Start-Job -ScriptBlock {
      param($B, $Id)
      try { Invoke-WebRequest -Uri ("{0}/api/subscriptions/{1}/events" -f $B,$Id) -UseBasicParsing -TimeoutSec 10 | Out-Null } catch { }
    } -ArgumentList $BaseUrl, $id
  }
  $null = Wait-Job -Job $jobs -Any -Timeout 15
  $null = Receive-Job -Job $jobs -ErrorAction SilentlyContinue
  $null = Wait-Job -Job $jobs -Timeout 15
  $jobs | Remove-Job -Force | Out-Null

  Start-Sleep -Milliseconds 300
  $m1 = Invoke-WebRequest -Uri "$BaseUrl/metrics" -UseBasicParsing -TimeoutSec 5
  $r1 = Get-MetricValue $m1.Content 'cp_sse_reconnects'
  $conn = Get-MetricValue $m1.Content 'cp_sse_connections'

  if ((($r1 - $r0) -lt $N) -or ($conn -ne 0)) { Write-Output ("FAIL: reconnects delta={0}, conns={1}" -f ($r1-$r0), $conn); exit 1 }
  Write-Output 'PASS'
  exit 0
} finally {
  try { if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force } } catch { }
}

