# 2025-10-06 12:58:30 RTSP+NVDEC 验证（Git Bash 双终端，用完即关）

- 目标
  - 验证 RTSP 源 + NVDEC 源路径在 GPU 模式下不再生成 CPU BGR（零拷贝输入），端到端运行稳定，帧数持续增长。

- 引擎设置（测试终端执行）
  - curl -s -H "Content-Type: application/json" -X POST http://127.0.0.1:8082/api/engine/set -d '{"type":"ort-cuda","device":0,"options":{"use_ffmpeg_source":false,"use_nvdec":true,"use_nvenc":true,"use_io_binding":true,"prefer_pinned_memory":true,"allow_cpu_fallback":true}}'

- 启停与测试步骤
  1) 后端终端（Git Bash）
     - cd video-analyzer/build/bin/Release
     - ./VideoAnalyzer.exe 'D:\\Projects\\ai\\cv\\video-analyzer\\build\\bin\\Release\\config'
  2) 测试终端（Git Bash）
     - python video-analyzer/test/scripts/check_single_mode.py --base http://127.0.0.1:8082 --engine ort-cuda --profile det_720p --url 'rtsp://127.0.0.1:8554/camera_01' --duration-sec 14 --warmup-sec 3 --timeout 10 --opts use_ffmpeg_source=false use_nvdec=true use_nvenc=true use_io_binding=true prefer_pinned_memory=true allow_cpu_fallback=true
  3) 观察 /api/pipelines processed_frames/fps，等待 14s 左右
  4) 结束后终止 VideoAnalyzer，删除两个会话（必要时直接 kill PID）

- 后端日志要点
  - [Factories] NVDEC preferred for URI rtsp://127.0.0.1:8554/camera_01
  - [Factories] NVDEC source constructed.
  - ORT CUDA IoBinding enabled (provider=cuda)
  - NVENC 打开成功；信令 8889 启停正常

- 测试结果
  - check_single_mode.py: [PASS] frames gained: 333
  - 实测 fps ≈ 25–43（含 RTSP 网络抖动与“RTP missed”日志），processed_frames 持续增长

- 备注
  - 相比文件源，RTSP 路径受网络与丢包影响，帧率波动较大；零拷贝路径下未观察到 CPU BGR 生成（NVDEC 源已直接填充 Frame.device）。
  - 后续将补充 NV12 设备端叠加（不绘制文字），并保持 CPU 回退完好。

