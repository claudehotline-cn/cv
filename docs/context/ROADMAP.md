# 路线图总览

- 里程碑 M0「联通与稳定」
  - 目标：VA 稳定调用 Triton；修复批次维错误与 SHM 初始问题。
  - 验收：视频有检测框；va_triton_rpc_failed_total 低于 2%；无持续 SHM 报错。

- 里程碑 M1「SHM 强化 + 自适配完善」
  - 目标：输出侧 SHM 全量可用、输入/输出解耦、按需字节绑定；补齐 ModelConfig 自适配（dtype/shape/max_batch）。
  - 验收：on_gpu 输出≥90%；无 SHM invalid args 重复报警；批次维自动正确。

- 里程碑 M2「性能与体验」
  - 目标：完成性能基线与对比工具；文档与排障完善；NMS 等后处理 GPU 直连。
  - 验收：SHM 相对 Host P50/P95 提升≥20%；FAQ 完整度≥90%。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| M0-T0 | 批次维自适配 | 错误指纹→自动切换 batch 维 | 误判→仅重试一次 | 批次错误清零 |
| M0-T1 | 输入 SHM 初版 | 稳定 cudaMalloc+ipc+D2D，唯一命名 | 设备号不符→server_dev 覆盖 | 注册失败率 <5% |
| M1-T0 | 输出 SHM 完备 | 一输出一 SHM；按需字节绑定 | 冲突→Unregister+唯一定名 | on_gpu 输出≥90% |
| M1-T1 | ModelConfig 自适配 | dtype/shape/max_batch 校验 | PB 缺失→降级日志 | 命中率≥95% |
| M2-T0 | 性能与压测 | Host vs SHM 对比脚本/报告 | 数据漂移→固定样本 | 提升≥20% |
| M2-T1 | 文档与排障 | 快速搭建/常见错误/FAQ | 版本变更→矩阵 | 自助完成度≥90% |

# 依赖矩阵

- 内部依赖：
  - video-analyzer（triton_session/node_model/NMS/Overlay）、lro、docs。
- 外部依赖（库/服务/硬件）：
  - Triton Server 25.08（HTTP/gRPC 可达）、CUDA 13、TensorRT 10（可选）、ONNX Runtime 1.23.2、OpenSSL 3、NVIDIA GPU（设备可见性一致）。

# 风险清单（Top-5）

- 设备号映射错误 → Triton 与 VA 的 CUDA_VISIBLE_DEVICES 不一致 → SHM invalid args → 显式 `shm_server_device_id` + 注册前 Unregister。
- Triton SDK/ABI 漂移 → 头/库不匹配 → 构建/运行错误 → 固定版本并以 ldd 自检。
- OpenSSL DSO 缺失 → 静态 gRPC 链接失败 → 使用共享 libgrpcclient.so 并补 libssl/libcrypto。
- 模型元数据偏差 → 自动填充 IO 名错误 → infer 无输出 → 强化日志并优先采用显式配置。
- 全局禁用 SHM → 性能退化不易察觉 → 输入/输出分侧禁用 + `reason=shm_*` 指标告警。
