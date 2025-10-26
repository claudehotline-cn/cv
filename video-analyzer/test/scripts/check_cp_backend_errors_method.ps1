param(
  [string]$BeforeText,
  [string]$AfterText,
  [string[]]$Expect # format: "service|method"
)

$ErrorActionPreference = 'Stop'

function Parse-BackendErrors($text) {
  $map = @{}
  foreach ($line in ($text -split "`n")) {
    $m = [regex]::Match($line, '^cp_backend_errors_total\{([^}]*)\}\s+([0-9.]+)$')
    if ($m.Success) {
      $labels = $m.Groups[1].Value
      $val = [double]$m.Groups[2].Value
      $svc = ''; $meth='';
      foreach ($kv in ($labels -split ',')) {
        $p = $kv -split '='
        if ($p.Length -ge 2) {
          $k = $p[0].Trim(); $v = $p[1].Trim('"')
          if ($k -eq 'service') { $svc = $v }
          elseif ($k -eq 'method') { $meth = $v }
        }
      }
      if ($svc -and $meth) {
        $key = "$svc|$meth"
        if (-not $map.ContainsKey($key)) { $map[$key] = 0 }
        $map[$key] += $val
      }
    }
  }
  return $map
}

$b = Parse-BackendErrors $BeforeText
$a = Parse-BackendErrors $AfterText

foreach ($k in $Expect) {
  $bv = ($b[$k] | ForEach-Object { $_ })
  if ($bv -eq $null) { $bv = 0 }
  $av = ($a[$k] | ForEach-Object { $_ })
  if ($av -eq $null) { $av = 0 }
  if ($av -le $bv) {
    Write-Error "backend_errors increment assertion failed: key='$k' before=$bv after=$av"
  }
}

Write-Host "[check_cp_backend_errors_method] PASS" -ForegroundColor Green
