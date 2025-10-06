# 2025-10-06 12:52:30 P0-STEP2 例行验证（Git Bash 双终端，按“用完即关”策略）

- 变更摘要
  - NVDEC 源：当解码得到设备端 NV12（AV_PIX_FMT_CUDA + sw_format=NV12）时，不再生成 CPU BGR，直接填充 Frame.device（width/height/pitch/data0,data1），作为 GPU 路径的零拷贝输入；无法满足条件时再回退到 CPU BGR（av_hwframe_transfer_data + sws_scale）。
  - 涉及文件：video-analyzer/src/media/source_nvdec_cuda.cpp

- 启停与测试步骤（本次全部在测试终端执行 HTTP/脚本；不使用 Postman）
  1) 启动后端（后端终端，Git Bash）
     - cd video-analyzer/build/bin/Release
     - ./VideoAnalyzer.exe 'D:\\Projects\\ai\\cv\\video-analyzer\\build\\bin\\Release\\config'
  2) 设置引擎（测试终端，Git Bash）
     - curl -s -H "Content-Type: application/json" -X POST http://127.0.0.1:8082/api/engine/set -d '{"type":"ort-cuda","device":0,"options":{"use_ffmpeg_source":true,"use_nvdec":true,"use_nvenc":true,"use_io_binding":true,"prefer_pinned_memory":true,"allow_cpu_fallback":true}}'
  3) 运行自动化测试（测试终端，Git Bash）
     - python video-analyzer/test/scripts/check_single_mode.py --base http://127.0.0.1:8082 --engine ort-cuda --profile det_720p --url 'D:\\Projects\\ai\\cv\\video-analyzer\\data\\01.mp4' --duration-sec 12 --warmup-sec 3 --timeout 10 --opts use_ffmpeg_source=true use_nvdec=true use_nvenc=true use_io_binding=true prefer_pinned_memory=true allow_cpu_fallback=true
  4) 结束与清理（执行完毕后）
     - 终止 VideoAnalyzer 进程（确保 8082/8889 端口释放）
     - 通过终端 API 删除两个 Git Bash 会话；若 API 返回 500，则直接 kill PID

- 本次结果
  - /api/engine/set: success=true, provider=ort-cuda
  - check_single_mode.py: [PASS] frames gained: 547，fps ≈ 46–51，processed_frames 持续增长
  - 后端日志：FFmpeg 源 + ORT CUDA IoBinding + NVENC，信令 8889 启停正常
  - 清理验证：8082/8889 无监听

- 备注
  - 本次使用文件源（01.mp4）验证端到端链路稳定性；NVDEC 改动将体现在 RTSP+NVDEC 路径上（GPU 模式不再生成 CPU BGR），待 RTSP 场景回归覆盖。
  - 后续继续 P0-STEP2：在 GPU 模式下选择 Passthrough 或 NV12 设备端叠加（不绘制文字），保持 CPU 回退完好；随后扩展到 YOLOv12 设备端后处理（P1）。

