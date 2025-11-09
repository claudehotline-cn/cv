# 路线图总览

- M0「内嵌 Triton 稳定性修复」
  - 目标：修复 In-Process 推理崩溃与生命周期问题，确保单帧/长时运行稳定。
  - 验收：连续运行≥24h 无崩溃；日志无重复 30s 关停等待；单路 RTSP 推理 FPS ≥ 设定阈值。
- M1「MinIO S3 仓库对接」
  - 目标：以 MinIO 托管模型仓库，In-Process 模式稳定加载与切换模型。
  - 验收：从 `s3://…/models` 成功加载模型；版本切换成功；网络波动下自动恢复。
- M2「可观测与运维完善」
  - 目标：完善日志与指标，支持一键部署与证书配置，形成可回滚方案。
  - 验收：提供部署文档与自动化脚本；关键指标与错误可在面板看到；回滚验证通过。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| P0 | In-Process 崩溃修复补丁 | 请求释放回调三参；异步后不手动 Delete；GPU/CPU 输出分配器 | 双重释放→回调接管；早期失败分支清理 | 连续推理 10 万帧无崩溃 |
| P1 | Server 生命周期稳定 | 会话持有 host shared_ptr；移除析构卸载 | 每帧销毁→共享持有；不误卸载 | 无 30s 等待日志，运行≥24h |
| P2 | S3 接入（MinIO） | Compose 引入 MinIO/mc；内嵌端点 S3 URL；路径样式强制 | 端点/区域解析差异→内嵌 URL 与多前缀环境 | 成功加载 `s3://…/models` |
| P3 | 连通与凭据校验 | 容器内 SigV4 自测；健康检查；最小调试日志 | 桶不存在/权限→自动初始化/指引 | 403/404→引导修复，200 成功 |
| P4 | 运维与回滚 | 显式模型控制或仓库轮询；TLS 配置 | 证书与权限→文档与脚本 | 切换/回滚成功率 100% |

# 依赖矩阵

- 内部依赖：
  - `video-analyzer`（In-Process Triton 集成）、`controlplane`（模型控制/切换）、`video-source-manager`、`web-frontend`、`lro`、Compose 脚本。
- 外部依赖（库/服务/硬件）：
  - Triton Server 2.60（libtritonserver）、CUDA 13、TensorRT、ONNX Runtime、MinIO（S3 兼容）、MySQL、Redis、RTSP 源、NVIDIA GPU、Docker/Compose。

# 风险清单（Top-5）

- S3 客户端初始化失败 → 端点/区域/样式不匹配 → SDK debug 日志异常或 “No response body” → 采用内嵌端点 URL + 强制 path-style；补齐 AWS_/S3_ 变量。
- 会话/Server 生命周期错配 → 每帧后销毁/30s 等待 → 日志出现 Triton 关停倒计时 → 会话持有 host（shared_ptr）；禁止析构卸载；增加就绪检查。
- 桶/模型不存在 → 404/AccessDenied → MinIO 403/404 与 KeyCount=0 → mc 初始化 bucket；文档化目录结构；启动前校验。
- 证书与安全配置不足 → HTTPS 校验失败或明文风险 → TLS 错误/抓包可见明文 → 启用 `S3_USE_HTTPS=1`、`S3_VERIFY_SSL=1`，挂载 CA 并校验。
- 性能回退或资源耗尽 → FPS 下滑/内存泄漏 → Prom 指标异常、GPU/内存报警 → 固化指标阈值；分阶段压测；启用引擎缓存与 pinned memory。

