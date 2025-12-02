Param(
  [int]$Port = 5500
)

$Backend = "mysql+pymysql://root:123456@127.0.0.1:13306/mlflow"
$ArtRoot = Join-Path (Get-Location) "logs/mlruns"
New-Item -ItemType Directory -Force -Path $ArtRoot | Out-Null

Write-Host "[mlflow] backend=$Backend artifact=file:$ArtRoot port=$Port"
try { python -m pip install --user --upgrade mlflow pymysql | Out-Null } catch {}
mlflow server --backend-store-uri $Backend --default-artifact-root "file:$ArtRoot" --host 0.0.0.0 --port $Port

