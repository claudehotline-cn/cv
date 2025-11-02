@echo off
setlocal

rem Usage: build_vsm.bat
rem  - gRPC 为必选依赖，由 CMake 内部强制启用；不再外部传参。

rem Detect vcpkg toolchain
if not defined VCPKG_ROOT set "VCPKG_ROOT=D:\Projects\vcpkg"
set "VCPKG_TOOLCHAIN=%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake"
if not exist "%VCPKG_TOOLCHAIN%" (
  echo [ERROR] vcpkg toolchain not found: "%VCPKG_TOOLCHAIN%"
  exit /b 1
)

rem Repo root (tools\..)
set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"
set "VSM_DIR=%REPO%\video-source-manager"
set "BUILD=%VSM_DIR%\build"

rem Locate Visual Studio with vswhere
set "VSWHERE=C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=* delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINST=%%i"
if not exist "%VSINST%\VC\Auxiliary\Build\vcvars64.bat" (
  echo [ERROR] vcvars64.bat not found: "%VSINST%\VC\Auxiliary\Build\vcvars64.bat"
  exit /b 1
)
call "%VSINST%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1

rem Prefer Ninja if available under repo tools
set "NINJA=%REPO%\tools\ninja.exe"
set "GEN="
if exist "%NINJA%" set "GEN=Ninja"

echo === Configuring VideoSourceManager (gRPC REQUIRED) ===
if "%GEN%"=="Ninja" (
  cmake -S "%VSM_DIR%" -B "%BUILD%" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE="%VCPKG_TOOLCHAIN%"
 ) else (
  cmake -S "%VSM_DIR%" -B "%BUILD%" -DCMAKE_TOOLCHAIN_FILE="%VCPKG_TOOLCHAIN%"
)
if errorlevel 1 exit /b 1

echo === Building VideoSourceManager ===
cmake --build "%BUILD%" -j
exit /b %ERRORLEVEL%
