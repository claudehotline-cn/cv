# 1) 载入 VS 环境（你已做过，但再执行一次确保当前会话生效）
& "H:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" amd64

# 2) 清理上次的 CMake 缓存（必须）
rmdir D:\Projects\ai\cv\video-analyzer\build-ninja -Recurse -Force

确认 3 个目录都存在（路径按你机器改动；版本号看你前面用的是 10.0.26100.0）：

H:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64
H:\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64
H:\Windows Kits\10\Lib\10.0.26100.0\um\x64   ← 这里有 kernel32.lib

# 3)添加运行环境
$env:PATH="H:\Windows Kits\10\bin\10.0.26100.0\x64;$env:PATH"


在 同一个 PowerShell 会话设置 LIB 和 INCLUDE（一口气配齐）：

# MSVC 版本号与 SDK 版本号按实际修改
$MSVC    = "H:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207"
$SDKVer  = "10.0.26100.0"
$SDKROOT = "H:\Windows Kits\10"

# 供 link.exe 搜库用
$env:LIB = @(
  "$MSVC\lib\x64",
  "$SDKROOT\Lib\$SDKVer\ucrt\x64",
  "$SDKROOT\Lib\$SDKVer\um\x64"
) -join ';'

# 供 cl.exe 头文件搜索用
$env:INCLUDE = @(
  "$MSVC\include",
  "$SDKROOT\Include\$SDKVer\ucrt",
  "$SDKROOT\Include\$SDKVer\um",
  "$SDKROOT\Include\$SDKVer\shared",
  "$SDKROOT\Include\$SDKVer\winrt",
  "$SDKROOT\Include\$SDKVer\cppwinrt"
) -join ';'

cmake -S D:\Projects\ai\cv\video-analyzer -B D:\Projects\ai\cv\video-analyzer\build-ninja -G Ninja `
  -DCMAKE_MAKE_PROGRAM=D:/Projects/ai/cv/tools/ninja.exe `
  -DCMAKE_TOOLCHAIN_FILE=D:/Projects/vcpkg/scripts/buildsystems/vcpkg.cmake `
  -DCMAKE_PREFIX_PATH=D:/Projects/vcpkg/installed/x64-windows `
  -DONNXRUNTIME_ROOT=D:/Projects/ai/cv/third_party/onnxruntime-win-x64-gpu-1.23.0 `
  -DCMAKE_BUILD_TYPE=Release