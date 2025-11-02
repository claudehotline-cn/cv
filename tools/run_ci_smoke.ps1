Param(
  [string]$BaseUrl = 'http://127.0.0.1:8082',
  [ValidateSet('auto','local','ci')]
  [string]$BuildMode = 'auto'
)
$ErrorActionPreference = 'Stop'

function Stop-VA {
  Get-Process -Name VideoAnalyzer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue | Out-Null
}

function Start-VA {
  Param([string]$ExtraEnv = '')
  $bin = Join-Path 'video-analyzer' 'build-ninja/bin/VideoAnalyzer.exe'
  $cfg = Join-Path 'video-analyzer' 'build-ninja/bin/config'
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = (Resolve-Path $bin)
  $psi.Arguments = (Resolve-Path $cfg)
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $false
  $psi.RedirectStandardError = $false
  foreach ($kv in @('VA_MODEL_REGISTRY_ENABLED','VA_MODEL_PREHEAT_ENABLED','VA_MODEL_PREHEAT_CONCURRENCY','VA_WAL_SUBSCRIPTIONS','VA_WAL_MAX_BYTES')) {
    $val = [System.Environment]::GetEnvironmentVariable($kv)
    if ($val) { $psi.Environment[$kv] = $val }
  }
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  [void]$p.Start()
  return $p
}

function Wait-Healthy {
  Param([int]$TimeoutSec = 10)
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + '/api/system/info') -TimeoutSec 2
      if ($r.code -eq 'OK') { return $true }
    } catch { Start-Sleep -Milliseconds 250 }
  }
  return $false
}

Write-Host '== Build VideoAnalyzer =='
if ($BuildMode -eq 'auto') {
  if (Test-Path "$Env:ProgramFiles(x86)\Microsoft Visual Studio\Installer\vswhere.exe") { $BuildMode = 'ci' } else { $BuildMode = 'local' }
}
if ($BuildMode -eq 'ci') {
  & powershell -ExecutionPolicy Bypass -File tools/build_va_ci.ps1 | Tee-Object -FilePath build_va_log.txt
} else {
  & tools/build_va_with_vcvars.cmd | Tee-Object -FilePath build_va_log.txt
}

Write-Host '== Test 0: LRO library CI (unit + examples) =='
try {
  & tools/run_lro_ci.ps1 -BuildMode local | Tee-Object -FilePath lro_ci_log.txt
} catch {
  throw "LRO CI failed: $_"
}

Write-Host '== Test 1: admin WAL endpoints (WAL enabled) =='
Stop-VA
# Enable WAL for this run
$Env:VA_WAL_SUBSCRIPTIONS = '1'
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for admin wal test' }
# Tail & summary quick check
python video-analyzer/test/scripts/check_admin_wal_tail.py
# While server is up, also run metrics+headers tests (requires requests)
try {
  python -m pip install --upgrade pip
  python -m pip install requests
  python video-analyzer/test/scripts/check_metrics_exposure.py --base $BaseUrl
  python video-analyzer/test/scripts/check_headers_cache.py --base $BaseUrl --timeout 5.0
  python video-analyzer/test/scripts/check_etag_race.py --base $BaseUrl --threads 8 --loops 20
  python video-analyzer/test/scripts/check_cancel_wal_and_stats.py --base $BaseUrl
} catch {
  Write-Warning "metrics/headers tests skipped or failed: $_"
}
Stop-VA

Write-Host '== Test 1b: minimal API once (POST→GET→DELETE + SSE) =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for minimal API test' }
try {
  python -m pip install --upgrade pip
  python -m pip install requests
} catch { Write-Warning "pip/requests install failed or skipped: $_" }
python video-analyzer/test/scripts/check_min_api_once.py --base $BaseUrl
Stop-VA

Write-Host '== Test 2: model registry preheat status =='
python video-analyzer/test/scripts/check_preheat_status.py

Write-Host '== Test 3: WAL scan after restart =='
# Keep WAL env enabled for scan test
$Env:VA_WAL_SUBSCRIPTIONS = '1'
python video-analyzer/test/scripts/check_wal_scan.py
Write-Host '== Test 3b: WAL rotation/TTL cross-restart evidence =='
python video-analyzer/test/scripts/check_wal_rotation_ttl.py

Write-Host '== Test 4: SSE cancel trace (minimal, no-frontend) =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for SSE cancel trace test' }
python video-analyzer/test/scripts/check_cancel_sse_trace.py --base $BaseUrl
Stop-VA

Write-Host '== Test 5: System info subscriptions echo =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for system info test' }
python video-analyzer/test/scripts/check_system_info_subs.py --base $BaseUrl
Stop-VA

Write-Host '== Test 6: Metrics histogram + failed reasons presence =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for metrics presence test' }
python video-analyzer/test/scripts/check_metrics_hist_and_reasons.py --base $BaseUrl --poll-sec 8
Stop-VA

Write-Host '== Test 6b: Admission fair window exposure (metrics + system info) =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for fair-window tests' }
python video-analyzer/test/scripts/check_fair_window_metric.py --base $BaseUrl --timeout 6.0
python video-analyzer/test/scripts/check_fair_window_info.py --base $BaseUrl --timeout 6.0
Stop-VA

Write-Host '== Test 7: Quotas snapshot与指标（M2） =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for quotas tests' }
python video-analyzer/test/scripts/check_quota_status.py --base $BaseUrl --timeout 6.0
python video-analyzer/test/scripts/check_quota_metrics.py --base $BaseUrl --timeout 6.0
Stop-VA

Write-Host '== Test 8: ACL scheme/profile（M2） =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for ACL tests' }
python video-analyzer/test/scripts/check_acl_profile_scheme.py --base $BaseUrl --timeout 6.0
python video-analyzer/test/scripts/check_exempt_bypass_acl.py --base $BaseUrl --timeout 6.0
python video-analyzer/test/scripts/check_key_overrides.py --base $BaseUrl --timeout 6.0
Stop-VA

Write-Host '== Test 9: per-key 灰度 observe/enforce（M2） =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for per-key gray tests' }
python video-analyzer/test/scripts/check_key_observe_only.py --base $BaseUrl --timeout 6.0 --tries 2
python video-analyzer/test/scripts/check_key_enforce_percent.py --base $BaseUrl --timeout 6.0 --tries 20
Stop-VA

Write-Host '== Test 10: 失败路径（RTSP 打开失败 / 模型加载失败） =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for fail-path tests' }
python video-analyzer/test/scripts/check_fail_rtsp_open.py --base $BaseUrl --timeout 10.0
python video-analyzer/test/scripts/check_fail_model_load.py --base $BaseUrl --timeout 10.0
Stop-VA

Write-Host '== Test 11: use_existing merge metrics（non_terminal/ready/miss） =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for merge metrics test' }
python video-analyzer/test/scripts/check_merge_metrics.py
Stop-VA

Write-Host '== Test 12: SSE connections/reconnects metrics =='
Stop-VA
$proc = Start-VA
if (-not (Wait-Healthy -TimeoutSec 12)) { throw 'VA not healthy for SSE metrics test' }
python video-analyzer/test/scripts/check_sse_metrics.py
Stop-VA

Write-Host '== Report: failed reasons unknown ratio (best-effort) =='
try {
  $outDir = Join-Path 'video-analyzer' 'build-ninja/bin/logs'
  if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
  $json = python video-analyzer/test/scripts/report_failed_unknown.py --base $BaseUrl
  $json | Out-File -FilePath (Join-Path $outDir 'report_failed_unknown.json') -Encoding utf8
  Write-Host 'saved' (Join-Path $outDir 'report_failed_unknown.json')
} catch {
  Write-Warning "report_failed_unknown failed: $_"
}

Write-Host 'All smoke tests passed.'

