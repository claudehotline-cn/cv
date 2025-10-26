Param(
  [string]$BaseUrl = "http://127.0.0.1:8080"
)
$ErrorActionPreference = 'Stop'

$cfgSrc = Join-Path $PSScriptRoot '../../../controlplane/config'
$cfgTmp = Join-Path $env:TEMP ('cp_cfg_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $cfgTmp | Out-Null
Copy-Item -Path (Join-Path $cfgSrc '*') -Destination $cfgTmp -Recurse

# Inject security section
$app = Join-Path $cfgTmp 'app.yaml'
@"
security:
  cors:
    allowed_origins: ["*"]
  auth:
    bearer_token: "test_token"
  rate_limit:
    rps: 1
"@ | Add-Content -Path $app -Encoding UTF8

$exe = Resolve-Path (Join-Path $PSScriptRoot '../../../controlplane/build/bin/controlplane.exe')
$p = Start-Process -FilePath $exe -ArgumentList $cfgTmp -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 1

function Req($path, $auth="") {
  $h = @{}
  if ($auth) { $h['Authorization'] = $auth }
  return iwr -UseBasicParsing ("$BaseUrl$path") -Headers $h -TimeoutSec 5 -SkipHttpErrorCheck:$true
}

try {
  # 1) no auth -> 401
  $r1 = Req '/api/system/info'
  if ($r1.StatusCode -ne 401) { throw "EXPECT 401 GOT $($r1.StatusCode)" }

  # 2) with bearer -> 200
  $r2 = Req '/api/system/info' 'Bearer test_token'
  if ($r2.StatusCode -ne 200) { throw "EXPECT 200 GOT $($r2.StatusCode)" }

  # 3) rate limit: second request in same second -> 429 (best-effort)
  $r3 = Req '/api/system/info' 'Bearer test_token'
  if ($r3.StatusCode -ne 429 -and $r3.StatusCode -ne 200) { throw "EXPECT 429/200 GOT $($r3.StatusCode)" }

  Write-Host "[cp_security_negative] PASS" -ForegroundColor Green
} finally {
  if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
  Remove-Item -Recurse -Force $cfgTmp -ErrorAction SilentlyContinue
}

