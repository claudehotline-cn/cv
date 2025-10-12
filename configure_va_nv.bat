@echo off
call "H:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake -S video-analyzer -B video-analyzer\build-ninja -G Ninja -DCMAKE_BUILD_TYPE=Release -DUSE_CUDA=ON -DWITH_NVDEC=ON -DWITH_NVENC=ON -DUSE_GRPC=ON -DVA_ENABLE_GRPC_SERVER=ON
if errorlevel 1 exit /b 1
"%~dp0tools\ninja.exe" -C video-analyzer\build-ninja -v
