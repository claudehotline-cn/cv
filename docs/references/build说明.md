如何稳定构建                                                                                                                                          

  - 一次性配置（Release，开启 gRPC 但关闭服务与单测）：                                                                                                 
      - 在 VS 开发者命令行中运行                                                                                                                        
      - cmake -S D:\Projects\ai\cv\video-analyzer -B D:\Projects\ai\cv\video-analyzer\build-ninja -G Ninja -DCMAKE_BUILD_TYPE=Release -DUSE_GRPC=ON     
        -DVA_ENABLE_GRPC_SERVER=OFF -DVA_BUILD_TESTS=OFF -DCMAKE_PREFIX_PATH=D:/Projects/vcpkg/installed/x64-windows -DCMAKE_IGNORE_PREFIX_PATH=H:/     
        anaconda3/Library -DProtobuf_DIR=D:/Projects/vcpkg/installed/x64-windows/share/protobuf -DgRPC_DIR=D:/Projects/vcpkg/installed/x64-windows/     
        share/grpc                                                                                                                                      
  - 构建：                                                                                                                                              
      - tools\build_with_vcvars.cmd D:\Projects\ai\cv\video-analyzer\build-ninja                                                                        
  - 结果：                                                                                                                                              
      - 已在本地完成上述配置与构建流程，VideoAnalyzer.exe 目标可成功生成（日志中已完成编译+链接，仅显示过程摘要）。 