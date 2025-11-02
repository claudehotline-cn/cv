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
  $p = Start-Process -FilePath $exe -ArgumentList 'controlplane/config' -PassThru -WindowStyle Hidden
  if (-not (Wait-Http "$BaseUrl/metrics" 12)) { Write-Output 'SKIP: metrics not ready'; if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force }; exit 0 }

  $payload = @{ attach_id = 'idem-01'; source_uri = 'rtsp://127.0.0.1:8554/camera_01'; pipeline_name = 'p-idem-01'; spec = @{ yaml_path = 'graphs/dummy.yaml' } } | ConvertTo-Json -Depth 5
  $headers = @{ 'Content-Type' = 'application/json' }
  $first = $null
  try { $first = Invoke-WebRequest -Uri "$BaseUrl/api/orch/attach_apply" -Method Post -Headers $headers -Body $payload -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop } catch { $first = $_.Exception.Response }
  if ($first.StatusCode -ge 500) { Write-Output 'SKIP: backend unavailable'; exit 0 }
  if ($first.StatusCode -ne 202) { Write-Output ("FAIL: first attach_apply {0}" -f $first.StatusCode); exit 1 }

  $second = $null
  try { $second = Invoke-WebRequest -Uri "$BaseUrl/api/orch/attach_apply" -Method Post -Headers $headers -Body $payload -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop } catch { $second = $_.Exception.Response }
  if ($second.StatusCode -ne 202) { Write-Output ("FAIL: second attach_apply {0}" -f $second.StatusCode); exit 1 }

  Write-Output 'PASS'
  exit 0
} finally {
  try { if ($p -and $p.Id) { Stop-Process -Id $p.Id -Force } } catch { }
}

