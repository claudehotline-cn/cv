Param(
  [Parameter(Mandatory=$true)][string]$BeforeJson,
  [Parameter(Mandatory=$true)][string]$AfterJson,
  [string[]]$ExpectKeys
)
$ErrorActionPreference = 'Stop'

$before = $BeforeJson | ConvertFrom-Json
$after = $AfterJson | ConvertFrom-Json

function Get-CounterValue([object]$obj, [string]$key) {
  if (-not $obj) { return 0 }
  $props = $obj.PSObject.Properties | Where-Object { $_.Name -eq $key }
  if ($props) { return [double]$props.Value } else { return 0 }
}

$bMap = $before.cp_request_total
$aMap = $after.cp_request_total

foreach ($k in $ExpectKeys) {
  $b = Get-CounterValue $bMap $k
  $a = Get-CounterValue $aMap $k
  if (($a - $b) -lt 1) {
    Write-Error "metrics increment assertion failed: key='$k' before=$b after=$a"
  }
}

Write-Host "[check_cp_metrics_increment] PASS" -ForegroundColor Green
