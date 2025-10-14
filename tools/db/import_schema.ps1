Param(
  [string]$Host = "127.0.0.1",
  [int]$Port = 13306,
  [string]$User = "root",
  [string]$Password = "123456",
  [string]$Database = "cv_cp",
  [string]$SchemaPath = "db/schema.sql"
)

Write-Host "[info] Importing schema from '$SchemaPath' into $User@$Host:$Port/$Database"
if (!(Test-Path $SchemaPath)) { Write-Error "schema file not found: $SchemaPath"; exit 1 }

function Has-Cmd($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

if (Has-Cmd 'mysql') {
  Write-Host "[info] Using local mysql client"
  $sql = Get-Content -Raw -Path $SchemaPath
  $env:MYSQL_PWD = $Password
  $args = @('-h', $Host, '-P', $Port, '-u', $User)
  $p = Start-Process -FilePath 'mysql' -ArgumentList $args -NoNewWindow -PassThru -RedirectStandardInput 'pipe' -RedirectStandardOutput 'pipe' -RedirectStandardError 'pipe'
  $p.StandardInput.WriteLine($sql)
  $p.StandardInput.Close()
  $p.WaitForExit()
  if ($p.ExitCode -ne 0) { Write-Error $p.StandardError.ReadToEnd(); exit $p.ExitCode }
  Write-Host "[ok] schema imported"
  exit 0
}

if (Has-Cmd 'docker') {
  Write-Host "[info] Local mysql not found; using docker mysql client"
  # On Docker Desktop for Windows, host.docker.internal resolves to the host
  $targetHost = if ($Host -eq '127.0.0.1') { 'host.docker.internal' } else { $Host }
  $sql = Get-Content -Raw -Path $SchemaPath
  $cmd = "mysql -h $targetHost -P $Port -u $User -p$Password"
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($sql)
  $si = New-Object System.Diagnostics.ProcessStartInfo
  $si.FileName = 'docker'
  $si.Arguments = "run --rm -i mysql:8.0 mysql -h $targetHost -P $Port -u $User -p$Password"
  $si.RedirectStandardInput = $true
  $si.RedirectStandardOutput = $true
  $si.RedirectStandardError = $true
  $si.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($si)
  $proc.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
  $proc.StandardInput.Close()
  $proc.WaitForExit()
  if ($proc.ExitCode -ne 0) { Write-Error $proc.StandardError.ReadToEnd(); exit $proc.ExitCode }
  Write-Host "[ok] schema imported via docker client"
  exit 0
}

Write-Warning "Neither 'mysql' nor 'docker' is available. Please import manually:"
Write-Host   "  1) Open MySQL Workbench/DBeaver, connect to $Host:$Port"
Write-Host   "  2) Execute $SchemaPath against database '$Database'"
exit 2

