# 路线图总览

- 里程碑 M0：TLS/mTLS 全链路打通（开发环境）
  - 目标：三后端默认启用 TLS/mTLS；证书路径配置化并转绝对；SNI=localhost；前端不使用 WHEP fallback。
  - 验收：start_stack_tls 成功；test_mtls_* 通过；订阅 API 正常；最小证据（截图/网络清单）归档。
- 里程碑 M1：稳定编排与可观测
  - 目标：VSM→VA 完整 gRPC 编排（attach/remove/subscribe）；指标齐备（by service,method,code）；前端能稳定观看。
  - 验收：持续 2 小时无 5xx/UNAVAILABLE 尖峰；WHEP 201 且 readyState≥2；Grafana 面板稳定。
- 里程碑 M2：零拷贝与 CI 验证
  - 目标：VA 零拷贝路径稳定（gpu_active=1，io_binding=1）；CI 覆盖 TLS/编排基本回归用例。
  - 验收：模型推理与 NMS 正常、FPS 达标；CI 绿灯并产生日志/证据工件。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | TLS/mTLS 打通 | 证书配置化；路径绝对化；SNI=localhost | 证书缺失/路径错 → 启动前校验 | 100% gRPC 握手成功 |
| P1 | gRPC 编排 | VSM→VA Apply/Remove/Subscribe | 兼容性问题 → 明确 proto 与超时 | attach 成功率≥99% |
| P1.5 | 可观测完善 | by(service,method,code) 指标；日志采样 | 日志噪声 → 限速与分级 | 关键接口 P50/P95 公开 |
| P2 | 前端取证 | WHEP 201；视频可播放 | 跨域/证书 → 预置受信 CA | readyState≥2/10s 内 |
| P3 | 零拷贝稳定 | ORT CUDA IoBinding；NMS CUDA | CUDA 环境缺失 → 禁回退显错 | GPU 活跃+IoBinding=1 |
| P4 | 基线 CI | TLS 连通与编排回归 | 构建依赖 → 缓存与镜像 | CI 绿灯/证据工件 |

# 依赖矩阵
- 内部依赖：
  - CP 配置加载与 gRPC 客户端（SNI 覆盖）
  - VA ConfigLoader/NodeModel（allow_cpu_fallback/use_io_binding）
  - VSM YAML 配置与 VA gRPC 客户端（mTLS）
- 外部依赖（库/服务/硬件）：
  - gRPC/Protobuf、OpenSSL、ONNX Runtime（含 CUDA EP）
  - vcpkg、CMake/MSVC、Node.js（前端 dev）
  - NVIDIA 驱动/CUDA 运行时、RTSP 源（摄像头/推流器）

# 风险清单（Top-5）
- 证书/路径不一致 → 启动/握手失败 → 启动前自检（文件存在+绝对路径） → 阻断启动并打印修复建议
- SNI 不匹配 → wrong version number → 客户端统一覆盖为 localhost → 证书 SAN 要含 DNS 与 IP
- CUDA 环境缺失 → CPU 回退或推理失败 → 禁用回退暴露根因；补齐 CUDA/ORT 动态库 → 观察 RuntimeSummary
- 模型输出与 NMS 偏差 → NMS 失败 → 核对 graph 配置、模型输出名/形状 → 增加形状/阈值日志
- 前端 WHEP 播放异常 → 跨域/证书/网络 → DevTools MCP 最小取证（网络≤10、截图落盘） → 快速定位与回滚

