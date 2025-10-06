# GPU 零拷贝执行路径（设计与落地计划）

> 目标：在存在 GPU 的运行环境中，视频帧主像素数据从解码到编码全程不经过 Host（CPU 内存），即“解码→预处理→推理→叠加→编码”零拷贝；在无 GPU 的环境下自动使用现有 CPU 路径。对外系统接口（订阅/退订、输出 H264、REST 形状）不改变。

## 一、当前实现现状（简述）
- 解码
  - NVDEC 源可拿到设备端 NV12 指针，但仍会 `av_hwframe_transfer_data + sws_scale` 生成 CPU BGR 供后续环节使用。
- 预处理
  - CUDA letterbox 已支持 NV12→NCHW FP32 的设备直通路径；失败时回退 Host staging。
- 推理
  - ORT CUDA + IoBinding 已接好；默认可能将输出搬回 Host（取决于 `device_output_views/stage_device_outputs`）。
- 后处理
  - 提供 CUDA NMS 能力，但需核对/补齐 YOLOv12 输出布局的设备端 decode；当前可接受短期在 Host 端做小体量张量处理。
- 叠加
  - CUDA 叠加目前为 CPU BGR→H2D→绘制→D2H，且文字在 CPU 绘制，不满足主像素零拷贝。
- 编码
  - NVENC 已启用 hwframes，但仍走 CPU BGR + `sws_scale` → hwframe 上传（H2D）。

## 二、目标路径与约束
- GPU 在时（provider 为 `cuda`/`tensorrt` 或检测到 CUDA）：
  - 源：NVDEC 输出设备 NV12，不生成 CPU BGR。
  - 预处理：CUDA letterbox（NV12→NCHW FP32）设备直通。
  - 推理：ORT CUDA + IoBinding，`device_output_views=true`，避免输出回 Host。
  - 后处理：阶段性允许在 Host 做小体量张量处理；中期补 YOLOv12 设备端 decode + CUDA NMS。
  - 叠加：仅在 NV12 上画矩形/遮罩（不绘制文字），保持设备 NV12。
  - 编码：NVENC 设备内 D2D（NV12 设备帧喂入），不做 `sws_scale`/H2D。
- 无 GPU 在时：沿用现有 CPU 路径（FFmpeg 源 + CPU 预/推/后 + CPU 叠加 + libx264）。
- 不改变系统架构与外部接口：仍为 REST 订阅/退订、输出 H264；内部按运行时状态选择 GPU/CPU 路径。

## 三、实施计划（按优先级）
### P0 最小闭环（主像素零拷贝成立）
1) NVDEC 源：GPU 模式不再生成 `frame.bgr`
- 检测到设备 NV12 时，仅填充 `Frame.device{data0,data1,pitch0,pitch1,width,height,fmt=NV12,on_gpu=true}`，跳过 `av_hwframe_transfer_data + sws_scale`。异常/配置下保留 CPU fallback。

2) NVENC 设备输入通道
- 为编码器新增“设备 NV12 喂入”路径：
  - 用 `hw_frames_ctx` 分配 NVENC 设备帧；
  - `cudaMemcpy2D`（D2D）从 NVDEC 的 NV12 平面复制到 NVENC 帧；
  - 发送编码。CPU 路径维持现状。

3) NV12 叠加（不绘制文字）
- 增加 NV12 矩形/半透明块 CUDA kernel（修改 Y/UV 两平面），GPU 模式默认启用。
- CPU 路径继续使用 OpenCV 叠加（可保留文字）。

4) 运行时分流（不改接口）
- 在工厂内部按 provider 自动选择：
  - GPU：NVDEC + CUDA letterbox + ORT IoBinding(device) + NV12 GPU 叠加 + NVENC；
  - CPU：FFmpeg/OpenCV 源 + CPU 预/推/后 + CPU 叠加 + libx264。
- 配置开关统一到 `engine.options`（`use_nvdec/use_nvenc/use_io_binding/device_output_views` 等），REST `/api/engine/set` 热切换仅影响新订阅。

### P1 完善（减少 Host 参与 + YOLOv12 对齐）
5) YOLOv12 CUDA 后处理
- 校准 YOLOv12 的输出张量布局（例如 `1×84×N`），实现设备端 decode + CUDA NMS，直接消费 ORT 设备输出；确保坐标缩放与 letterbox 一致。

6) 稳定性与容错
- 任一环节失败或资源不足时，平滑回退到相邻的 CPU 路径（例如叠加失败→Passthrough，NVENC 失败→libx264）。

### P2 增强（可选）
7) 统一开关与运行时摘要
- `engine.options`：`use_nvdec/use_nvenc/use_io_binding/device_output_views/render_cuda_nv12` 等；
- 在日志首帧/链路建立时打印一次摘要：“NVDEC→CUDA letterbox→ORT IoBinding(device)→NV12 overlay→NVENC device feed”，便于快速判定路径（不新增外部 API）。

8) 前端文字渲染（如需）
- 后端不改接口、不改视频流。如需文字，建议前端基于检测元数据（如已有 DataChannel）渲染；后续再评估 GPU 位图字体（小字符集）。

## 四、运行时行为（自动分流）
- GPU 环境：
  - provider 为 `cuda`/`tensorrt` 或检测到 CUDA，默认走 GPU 零拷贝链路；
  - `engine.options` 可用于细粒度开关；新订阅生效，已运行管线不强切。
- 无 GPU 环境：
  - 自动回退 CPU 路径；保持功能和结果一致。

## 五、验收标准
- GPU：
  - 帧主像素数据不经过 Host；不出现 `sws_scale/H2D`（像素数据）在 GPU 路径；
  - fps/帧增长稳定；日志可见 GPU 路径摘要；
  - 允许短期 D2H（小体量模型输出）直至 P1 完成。
- CPU：
  - 全流程 CPU 正常；叠加可含文字；结果一致。
- 结果一致性：
  - GPU/CPU 后处理框/分数在容忍范围内一致（坐标缩放对齐）。

## 六、测试与回归
- 单流对比：
  - GPU（IoBinding 开/关）与 CPU 各跑 10–30s，观察 `/api/pipelines` 的 `processed_frames/fps` 持续增长；
  - GPU 零拷贝链路下，检查日志不出现像素数据的 Host 往返。
- 稳定性：
  - 多流（2–4）并发与长时（≥30min）运行；NVDEC/NVENC 热切换、新订阅稳定。
- 功能一致性：
  - 用固定视频与 YOLOv12 模型，核对 GPU/CPU 后处理输出差异在允许范围。

## 七、风险与规避
- NVDEC/NVENC 平台依赖：需要 FFmpeg 构建包含 `ffnvcodec`，CUDA 版本匹配；
- YOLOv12 输出布局差异：需要针对模型变体核对 decode 逻辑；
- NV12 叠加一致性：不同显示器/播放器对 NV12 渲染偏差需留意（颜色空间/范围）。

## 八、落地顺序与里程碑
1) P0：打通 **NVDEC → CUDA letterbox → ORT IoBinding(device) → NV12 GPU 叠加（无字） → NVENC(设备喂入)**，形成主像素零拷贝闭环；
2) P1：补 YOLOv12 设备端 decode + CUDA NMS，减少 Host 参与；
3) P2：统一开关与日志、前端文字渲染（如需）。

---

如需，我可以按 P0 先行提交最小改动补丁（仅内部切换，不改外部接口），确保“有 GPU 走零拷贝、无 GPU 走 CPU”成立，再逐步推进 P1/P2。

## 2025-10-06 02:20:00 P0-STEP1 测试记录（NVENC 设备 NV12 喂入）

- 改动摘要
  - 为 NVENC 增加“设备 NV12 直接喂入”路径：检测到 `Frame.has_device_surface=true` 且 `fmt=NV12` 时，分配 NVENC CUDA hwframe，并通过 `cudaMemcpy2D` 将 NV12 的 Y/UV 平面设备内（D2D）拷贝到 hwframe 后直接编码；失败则回退原 CPU BGR→sws→上传路径。
  - 文件：`video-analyzer/src/media/encoder_h264_ffmpeg.cpp`

- 测试步骤
  1) 启动后端（绝对路径，避免工作目录误差）
     - 命令：`D:\Projects\ai\cv\video-analyzer\build\bin\Release\VideoAnalyzer.exe D:\Projects\ai\cv\video-analyzer\build\bin\Release\config`
  2) 通过 HTTP 配置运行环境（Postman 执行）
     - POST `http://127.0.0.1:8082/api/engine/set`
       - JSON：
         ```json
         {
           "type": "ort-cuda",
           "device": 0,
           "options": {
             "use_ffmpeg_source": true,
             "use_nvdec": true,
             "use_nvenc": true,
             "use_io_binding": true,
             "device_output_views": true,
             "prefer_pinned_memory": true,
             "allow_cpu_fallback": true
           }
         }
         ```
  3) 订阅（Postman 执行；二选一）
     - 文件源：
       - POST `http://127.0.0.1:8082/api/subscribe`
       - JSON：`{"stream_id":"zc_gpu_test","profile":"det_720p","url":"D:\\Projects\\ai\\cv\\video-analyzer\\data\\01.mp4"}`
     - RTSP 源：
       - POST `http://127.0.0.1:8082/api/subscribe`
       - JSON：`{"stream_id":"zc_gpu_rtsp","profile":"det_720p","url":"rtsp://127.0.0.1:8554/camera_01"}`
  4) 验证（Postman 执行）
     - GET `http://127.0.0.1:8082/api/system/info`（provider=ort-cuda；ffmpeg_enabled=true）
     - GET `http://127.0.0.1:8082/api/pipelines`（观察 `processed_frames` 与 `fps` 持续增长）
  5) Python 脚本快速校验（终端执行）
     - 命令：
       ```bash
       python video-analyzer/test/scripts/check_single_mode.py \
         --base http://127.0.0.1:8082 \
         --no-set-engine \
         --profile det_720p \
         --url D:\Projects\ai\cv\video-analyzer\data\01.mp4 \
         --duration-sec 12 --warmup-sec 3 --timeout 10
       ```

- 期望与结果
  - 期望：/api/pipelines 中 `processed_frames` 持续增长；日志显示 NVENC 打开成功；GPU 机上帧率稳定（30–40fps 量级，仅示例）。
  - 实测：帧数在增长，订阅后服务可正常响应其它 API。

- 备注
  - 本步骤仅完成“编码端设备帧喂入”（去除像素数据的 Host 上传）；下一步将关闭 NVDEC 源在 GPU 路径下的 CPU BGR 生成，并采用 GPU NV12 画框（不绘文字）或 Passthrough，以打通主像素数据零拷贝闭环。

## 2025-10-06 P0-STEP1: 为 NVENC 增加设备 NV12 喂入路径（零拷贝闭环铺垫）
- 目标：在不改变对外接口前提下，使编码器在检测到帧携带设备端 NV12 (Frame.has_device_surface=true) 时，直接以 NVENC 硬件帧喂入（设备内 D2D 拷贝），避免 CPU BGR + sws_scale + H2D。
- 改动：
  - video-analyzer/src/media/encoder_h264_ffmpeg.cpp
    - 启用 CUDA 运行时头；
    - 在 encode() 中，当满足 use_hwframes_ && hw_frames_ctx_ && frame.device(f=NV12,on_gpu) 时：
      - 分配 NVENC CUDA hwframe；
      - 使用 cudaMemcpy2D 将 NV12 的 Y/UV 平面 D2D 拷贝到 hwframe；
      - 直接 avcodec_send_frame 发送设备帧；
      - 失败则回退原 CPU 路径。
- 测试：
  - 本地完成 Release 构建；
  - 建议你在目标机（含 CUDA+NVENC）执行：
    - set VA_USE_FFMPEG_SOURCE=1 && set VA_USE_NVDEC=1
    - 启动后端并用文件或 RTSP 订阅，观察日志：NVENC 正常编码；帧率稳定增长；
    - 进一步用 check_single_mode.py 做 10–12s smoke（GPU 模式）。
- 备注：
  - 此步未移除 NVDEC 源的 CPU BGR 生成，下一步将按 GPU 路径跳过该复制，形成“主像素零拷贝”闭环；
  - 叠加阶段在 GPU 模式下建议采用 Passthrough 或后续的 NV12 画框（不绘制文字）。
## 测试记录 — 2025-10-06 15:50:00
- 场景: RTSP 推流就绪后的端到端验证 (det_720p)
- 引擎设置: POST /api/engine/set
```json
{"type":"ort-cuda","device":0,"options":{"use_ffmpeg_source":true,"use_nvdec":true,"use_nvenc":true,"use_io_binding":true,"prefer_pinned_memory":true,"allow_cpu_fallback":true}}
```
- 订阅: POST /api/subscribe
```json
{"stream_id":"rtsp_now","profile":"det_720p","url":"rtsp://127.0.0.1:8554/camera_01"}
```
- 轮询: GET /api/pipelines（三次，间隔 3s）
  - T0: processed_frames≈50, fps≈42.12, connected=true, packets≈48
  - T+6s: processed_frames≈228, fps≈25.48, connected=true, packets≈222
  - T+3s(再次): processed_frames≈458, fps≈26.12, connected=true, packets≈444
- 结论: 帧数持续增长，RTSP 流处理正常；依赖已就绪（FFmpeg/OpenCV/datachannel/juice/jsoncpp/zlib/jpeg/ORT 已拷贝至 bin）。
