@echo off
call "H:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DUSE_GRPC=ON -DCMAKE_TOOLCHAIN_FILE=D:/Projects/vcpkg/scripts/buildsystems/vcpkg.cmake
if errorlevel 1 exit /b 1
"%~dp0..\tools\ninja.exe" -C build -v
