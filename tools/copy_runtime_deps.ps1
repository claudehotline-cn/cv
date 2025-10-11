param(
  [Parameter(Mandatory=$true)][string]$BinDir,
  [string]$OnnxRuntimeRoot = "",
  [string]$VcpkgRoot = "",
  [string]$FfmpegRoot = "",
  [string]$OnnxRuntimeDllDir = ""
)

function Copy-IfExists {
  param([string]$Src, [string]$Dst)
  if (Test-Path -LiteralPath $Src) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dst) | Out-Null
    Copy-Item -LiteralPath $Src -Destination $Dst -Force -ErrorAction SilentlyContinue | Out-Null
  }
}

function Copy-DllsFromDir {
  param([string]$Dir, [string]$Pattern = '*.dll')
  if (-not (Test-Path -LiteralPath $Dir)) { return }
  Write-Host "[deps] copy $Pattern from $Dir" -ForegroundColor Cyan
  Get-ChildItem -LiteralPath $Dir -Filter $Pattern -File -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-IfExists $_.FullName (Join-Path $BinDir $_.Name)
  }
}

Write-Host "[deps] target bin dir: $BinDir" -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# 1) ONNX Runtime providers (search flexible layouts)
function Resolve-OrtDllDir {
  param([string]$Root, [string]$DllDir)
  $candidates = @()
  if ($DllDir) { $candidates += $DllDir }
  if ($Root) {
    $candidates += (Join-Path $Root 'lib')
    $candidates += (Join-Path $Root 'bin')
    $candidates += $Root
    $candidates += (Join-Path $Root 'build\Windows\Release\Release')
    $candidates += (Join-Path $Root 'build\Windows\Release')
  }
  foreach ($d in $candidates) {
    if ($d -and (Test-Path -LiteralPath $d)) {
      if (Test-Path -LiteralPath (Join-Path $d 'onnxruntime.dll')) { return $d }
    }
  }
  # fallback: try to locate recursively
  if ($Root -and (Test-Path -LiteralPath $Root)) {
    $found = Get-ChildItem -LiteralPath $Root -Recurse -Filter 'onnxruntime.dll' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return (Split-Path -Parent $found.FullName) }
  }
  return $null
}

$ortDir = Resolve-OrtDllDir -Root $OnnxRuntimeRoot -DllDir $OnnxRuntimeDllDir
if ($ortDir) {
  Copy-DllsFromDir $ortDir 'onnxruntime*.dll'
}

# 2) FFmpeg prebuilt DLLs
if (-not $FfmpegRoot -or -not (Test-Path -LiteralPath $FfmpegRoot)) {
  $FfmpegRoot = Join-Path (Split-Path -Parent $PSScriptRoot) '..\third_party\ffmpeg-prebuilt\ffmpeg-master-latest-win64-lgpl-shared'
}
$ffmpegBin = Join-Path $FfmpegRoot 'bin'
Copy-DllsFromDir $ffmpegBin '*.dll'

# 3) vcpkg runtime DLLs (ixwebsocket/datachannel/mbedtls/usrsctp/opencv/zlib/ssl/crypto)
$vcpkgBins = @()
if ($VcpkgRoot) {
  $vcpkgBins += Join-Path $VcpkgRoot 'installed\x64-windows\bin'
}
$vcpkgBins += 'D:\Projects\vcpkg\installed\x64-windows\bin'
$vcpkgBins += 'H:\Program Files\Microsoft Visual Studio\2022\Community\VC\vcpkg\installed\x64-windows\bin'
$vcpkgBins | ForEach-Object { Copy-DllsFromDir $_ '*.dll' }

# 4) CUDA runtime (cudart 等)，可选拷贝，若存在则复制最小集
$cudaBins = @()
if ($env:CUDA_PATH) { $cudaBins += (Join-Path $env:CUDA_PATH 'bin') }
$cudaBins += 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin'
$cudaBins += 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin'
foreach ($cbin in $cudaBins) {
  Copy-DllsFromDir $cbin 'cudart64_*.dll'
  Copy-DllsFromDir $cbin 'nvrtc64_*.dll'
  Copy-DllsFromDir $cbin 'cublas64_*.dll'
  Copy-DllsFromDir $cbin 'cublasLt64_*.dll'
}

# 5) cuDNN（若本机安装并在常见路径，尽量拷贝；若未安装，跳过）
$cudnnCandidates = @(
  'C:\Program Files\NVIDIA\CUDNN\bin',
  'C:\Program Files\NVIDIA\cuDNN\bin'
)
$cudnnCandidates | ForEach-Object { Copy-DllsFromDir $_ 'cudnn*.dll' }

# 6) NVENC API（通常在系统目录）
Copy-IfExists 'C:\Windows\System32\nvEncodeAPI64.dll' (Join-Path $BinDir 'nvEncodeAPI64.dll')

Write-Host "[deps] copy done." -ForegroundColor Green
