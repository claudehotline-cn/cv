# 路线图总览

- M0「内嵌 Triton 稳定性修复」
  - 目标：修复 In‑Process 崩溃与生命周期问题；补齐 ServerOptions 与 I/O 基建，确保长稳运行。
  - 验收：连续运行≥24h 无崩溃；无 30s 关停等待；单路 RTSP 推理 FPS 达到既定阈值。
- M1「模型仓库与发布链路对接」
  - 目标：以 MinIO 托管模型仓库，打通 Load/Unload/Poll 与 SetEngine/HotSwap 的统一发布路径；前端具备发布/模型库操作。
  - 验收：`s3://…/models` 加载成功；前端可发布与回滚；仓库操作返回 OK。
- M2「可观测与调优闭环」
  - 目标：提供运行态与指标汇总接口，形成 perf_analyzer → 推荐 → 配置 的闭环；补齐回退/降级脚本。
  - 验收：Summary 卡片反映真实请求/缓存；perf 报告生成推荐批次；回退/降级脚本演练通过。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| P0 | In‑Process 修复补丁 | 释放回调三参；异步后不 Delete；GPU/CPU 分配器 | 双重释放→回调接管 | 连续推理 10 万帧无崩溃 |
| P1 | 生命周期稳定 | 会话持有 host shared_ptr；禁止析构卸载 | 每帧销毁→共享持有 | 无 30s 等待，24h 稳定 |
| P2 | S3 接入（MinIO） | 内嵌 S3 URL；多前缀环境变量；路径样式 | 端点/区域差异→内嵌 URL | 成功加载 `s3://…/models` |
| P3 | 发布与仓库控制 | `/api/control/set_engine|release` + `/api/repo/*` | HTTP→gRPC 映射；HotSwap 兼容 | 发布/回滚成功，HTTP 2xx |
| P4 | 可观测与调优 | `/api/_metrics/summary`、perf 封装与推荐 | 指标缺口→先 Summary 后 Grafana | 推荐批次落地且 P90 受控 |

# 依赖矩阵

- 内部依赖：
  - `video-analyzer`（In‑Process Triton）、`controlplane`（路由/汇总/桥接）、`web-front`（UI）、`lro`、工具脚本。
- 外部依赖（库/服务/硬件）：
  - Triton Server（libtritonserver）、CUDA、TensorRT、ONNX Runtime、MinIO（S3 兼容）、MySQL、Redis、RTSP 源、NVIDIA GPU、Docker/Compose、浏览器（前端）。

# 风险清单（Top-5）

- S3 端点/区域不匹配 → 仓库加载失败 → AWS SDK debug 异常/403/404 → 采用内嵌端点 + 强制 path‑style；补齐 AWS_/S3_ 变量。
- 生命周期错配 → 每帧销毁/30s 等待 → Triton 关停倒计时日志 → 会话持有 host；禁止析构卸载；就绪检查。
- 仓库目录/版本缺失 → 404/AccessDenied → MinIO KeyCount=0 → mc 初始化 bucket；标准化目录结构；启动前校验。
- 安全配置不足 → 明文/证书错误 → TLS 报错/抓包可见明文 → 启用 TLS（S3_USE_HTTPS/VERIFY_SSL），挂载 CA；密钥下发归档。
- 性能回退/资源耗尽 → FPS 下滑/显存抖动 → P95 异常、OOM → perf 分阶段压测；显存池/engine cache；动态批推荐落地。
