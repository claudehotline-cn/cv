@echo off
call "H:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build-cli -G Ninja -DUSE_GRPC=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE=D:/Projects/vcpkg/scripts/buildsystems/vcpkg.cmake
if errorlevel 1 exit /b 1
"%~dp0tools\ninja.exe" -C build-cli -v
