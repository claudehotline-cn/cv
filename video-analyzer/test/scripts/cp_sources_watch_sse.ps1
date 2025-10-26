Param(
  [string]$CpBase = "http://127.0.0.1:8080"
)
$ErrorActionPreference = 'Stop'

# Open SSE stream and ensure we receive at least one 'event: state' line
$url = "$CpBase/api/sources/watch_sse"
$req = [System.Net.HttpWebRequest]::Create($url)
$req.Method = 'GET'
$req.Timeout = 15000
$req.ReadWriteTimeout = 15000
$resp = $req.GetResponse()
try {
  if ([int]$resp.StatusCode -ne 200) { throw "status=$([int]$resp.StatusCode)" }
  $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
  $found = $false
  $deadline = [DateTime]::UtcNow.AddSeconds(10)
  while ([DateTime]::UtcNow -lt $deadline) {
    $line = $sr.ReadLine()
    if ($null -eq $line) { Start-Sleep -Milliseconds 50; continue }
    if ($line.StartsWith('event: state')) { $found = $true; break }
  }
  if (-not $found) { throw "no state event within 10s" }
} finally {
  $resp.Close()
}

Write-Host "[cp_sources_watch_sse] PASS" -ForegroundColor Green

