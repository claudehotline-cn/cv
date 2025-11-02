Param(
  [string]$CpBase = "http://127.0.0.1:8080"
)
$ErrorActionPreference = 'Stop'

$resp = iwr -UseBasicParsing "$CpBase/metrics" -TimeoutSec 8
$text = $resp.Content -replace "\r",""

$map = @{}
foreach ($line in $text.Split("`n")) {
  if ($line -match '^cp_request_total\{([^}]*)\}\s+([0-9.]+)$') {
    $labels = $Matches[1]
    $val = [double]$Matches[2]
    $route = ""; $method = ""; $code = ""
    foreach ($pair in $labels.Split(',')) {
      if ($pair -match '^(\w+)="([^"]*)"$') {
        $k = $Matches[1]; $v = $Matches[2]
        switch ($k) {
          'route' { $route = $v }
          'method' { $method = $v }
          'code' { $code = $v }
        }
      }
    }
    if ($route -and $method -and $code) {
      $key = "$route|$method|$code"
      $map[$key] = $val
    }
  }
}

$out = @{ cp_request_total = $map }
$out | ConvertTo-Json -Compress

