# 路线图总览

- M0「零拷贝打通」：默认启用 IoBinding 与 CUDA 预处理，GPU Provider 下统一计算流；以小模型（n 版）跑通 NVDEC→CUDA 预处理→ORT（CUDA）→GPU NMS→CUDA 叠加/编码。
  - 验收：日志含 provider=cuda、io_bind/dev_bind=true；`ort.run` 输出>0，`ms.node_model out_count>0`；Prom 指标 `va_d2d_nv12_frames_total` 递增。
- M1「模型兼容稳定」：以目标模型（x 版等）在无 NMS 导出形态下稳定产出 det_raw；可选启用 ORT TensorRT EP。
  - 验收：`analyzer.ort load` 显示 outputs≥1 且 out names 可见；GPU NMS 正常，端到端 FPS 达标（≥30FPS@720p）。
- M2「可观测与自动化」：细化日志与指标、CP 端到端脚本化验证、文档完善与回归测试集。
  - 验收：5 分钟内出具端到端验证证据（日志/指标/截图）；流水线切换（暂停/实时/换模）稳定且无回退 CPU。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| P0 | GPU 镜像与构建链路 | Dockerfile.gpu 以 cudnn-runtime；ORT 1.23.2 源码（CUDA，架构"90;120"）；可选 TRT | CUDA/cuDNN/TRT 依赖不匹配 → 固定版本与镜像源 | 镜像构建成功；VA 进程健康 |
| P1 | 零拷贝默认打通 | IoBinding 默认开启；CUDA 预处理；设备视图输出（device_output_views） | 设备/主机内存视图不一致 → 关闭 stage_device_outputs | provider=cuda；io_bind/dev_bind=true |
| P2 | 模型产出稳定 | 使用无 NMS 且有 Graph 输出的 ONNX；det_raw→NMS | 模型无输出/外部权重缺失 → 更换/补全模型 | `out_count>0`；`ort.run outputs>0` |
| P3 | GPU NMS/叠加压测 | GPU NMS + CUDA 叠加；NVENC 零拷贝 | GPU 内存峰值/流竞争 → 统一 CUDA 流/限流 | 720p ≥30FPS；无回退 CPU |
| P4 | 可选 TRT 路径 | ORT TRT EP；必要时解析 TRT 输出 | TRT 依赖/EP 不可用 → 回退 CUDA | TRT EP 可加载且稳定 |
| P5 | 观察与自动化 | 指标完善、CP 脚本、故障注入 | 采集不足 → 日志/指标细化 | 5 分钟交付端到端证据 |

# 依赖矩阵

- 内部依赖：
  - VA（analyzer/multistage、ORT session、CUDA 预处理/叠加、NMS）、CP（订阅/切换/换模）、VSM（可选 RTSP 源）。
- 外部依赖（库/服务/硬件）：
  - CUDA 12.9、cuDNN（cudnn-runtime）、（可选）TensorRT dev；ONNX Runtime 1.23.2 源码；FFmpeg；NVIDIA GPU（RTX 5090d 等）；MySQL、Redis（CP 环境）。

# 风险清单（Top-5）

- 模型无 Graph 输出 → 导出/打包异常或内置 NMS → 监控日志 `outputs=0`/`zero declared outputs` → 使用 `nms=False` 的 ONNX；补齐 external data。
- TRT 依赖不匹配 → EP 加载失败/回退 → 监控 `provider resolved` 与 EP 错误 → 固定镜像版本、仅在依赖齐备时启用 TRT。
- GPU 视图不一致 → NMS/叠加读取失败 → 监控 `device_views/stage_outputs` 与 `on_gpu` → 开启 device_output_views，关闭 stage。
- 构建/镜像陈旧 → 新日志缺失/行为不一致 → 监控二进制时间戳与 `analyzer.ort load` 的新字段 → 强制无缓存构建与版本标识。
- 网络受限 → 容器内依赖安装失败 → 监控 apt/pip 日志 → 预构建镜像，避免运行时拉取。

