Video Source Manager (skeleton)

本目录为 VSM 骨架，当前不参与构建。后续将实现：

- proto/source_control.proto：Attach/Detach/GetHealth
- src/app/controller/source_controller.*：会话管理
- adapters/inputs/ffmpeg_rtsp_reader.*：RTSP 读取
- adapters/outputs/to_analyzer_link.*：向 analyzer 推送帧（后续替换为共享内存/IPC/gRPC 流）

