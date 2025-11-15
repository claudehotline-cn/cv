# Triton 集成 WBS（Work Breakdown Structure）

## 0. 前置准备（0.5d）
- 依赖清单与工具链确认：Triton C++ gRPC Client、gRPC/Protobuf、CUDA 版本匹配。
- Compose 验证：可启动 `tritonserver`（8001/8000）并加载示例模型仓库 `/models`。
- 风险预案：网络可达性、证书（如启用 TLS）、镜像大小与拉取速度。

## 1. 设计收敛（0.5d）
- 确认接入点：新增 `TritonGrpcModelSession`（实现 `IModelSession`）。
- 工厂映射：`engine.provider=triton|triton-grpc` → Triton 会话。
- 配置键：`triton_url/model/model_version/input/outputs/timeout_ms/shm_cuda/cuda_shm_bytes`。
- 验收：评审 `docs/design/subscription_pipeline/triton_inprocess_integration.md`（含附录 A：gRPC 集成概要）与 WBS 一致。

## 2. T0 功能实现：gRPC + Host 内存（1.5d）
- 新增文件：`src/analyzer/triton_session.hpp/.cpp`（Host 内存路径）。
- `loadModel()`：连接、拉取 metadata/config、缓存 IO 名称与 dtype/shape。
- `run()`：将 `TensorView` host 拷入请求；解析输出映射为 host `TensorView`。
- `getRuntimeInfo()`：`provider=triton-grpc`，`gpu_active=false`（T0）。
- 工厂接入：`model_session_factory` 识别 provider 并注入 options。
- 验收：单路 720p E2E boxes>0，无异常日志。

## 3. 可观测与回退（0.5d）
- 指标：`va_triton_rpc_seconds`（直方图）与 `va_triton_rpc_failed_total`（按 reason 标签）。
- 日志：节流打印 `model/bytes/ms` 与失败指纹（timeout/unavailable/invalid）。
- 回退链：在 NodeModel 打开失败或 `run` 异常时降级到 ORT-TRT → CUDA。
- 验收：/metrics 出现新指标，Triton 不可用时自动回退。

## 4. 配置与 Compose（0.5d）
- Compose 新增 `triton` 服务（`gpus: all`、挂载 `/models`）。
- VA 示例配置：`engine.provider=triton` + `engine.options.triton_*`。
- 文档：`docs/examples/benchmark.md` 增加 triton 示例与常见问题。
- 验收：`docker compose up` 后 VA 可连通 Triton、可推理。

## 5. T1 性能化：CUDA SHM（2.0d）
- 输入 SHM：按首次输入尺寸注册/复用，容量不足触发重注册。
- 输出 SHM：为主要输出注册并复用；映射为设备侧 `TensorView`。
- 流/同步：在提交 RPC 前等待预处理 CUDA 流写入完成；请求完成后安全消费。
- 验收：720p 场景延迟下降（infer 阶段 P50/P95 优于 Host 方案）。

## 6. T2 深化（2.0d）
- 动态形状/批量：对接模型配置；容量与重注册策略完善。
- Ensemble（可选）：NMS/Overlay 迁至 Triton；或保留 VA 侧实现。
- 健壮性：熔断、重试、健康探测（定期 `ServerLive/Ready`）。
- 验收：长稳 30 分钟以上、失败计数可控、回退链与熔断配合良好。

## 7. 基准与报告（0.5d）
- 采样：使用 `video-analyzer/test/scripts/benchmark_metrics.py` 对 cuda/tensorrt/triton 各采 30–60s。
- 产出：FPS、`va_frame_latency_ms` P50/P95、`va_triton_rpc_seconds` 汇总。
- 文档：填充 `docs/plans/benchmark-report-template.md`，附关键指标截图。
- 验收：提交基准报告与配置复现实录。

## 8. CI/回归（0.5d）
- 烟测脚本：最小 gRPC 请求成功与 /metrics 出新指标；异常场景（Triton 宕机）触发回退。
- 可选：在专用 runner 上接入 GPU/容器化测试。
- 验收：CI 能跑通基础用例，失败给出清晰指纹。

## 9. 风险与回滚（持续）
- 依赖不可用：回退至 ORT-TRT/CUDA；禁用 provider=`triton`。
- 性能不达标：保留原路径；开启/关闭 CUDA SHM 作为开关项。
- 回滚方案：按提交粒度最小化（单文件会话实现与工厂映射可独立回滚）。

## 里程碑与人天估算
- M0（功能）：~3d（含设计收敛）
- M1（性能）：~2d
- M2（深化）：~2d
- 基准/CI/文档：~1.5d
- 总计：~8.5d（以 1 人为基准）

## 验收清单（按阶段）
- M0：E2E boxes>0；/metrics 出现 `va_triton_rpc_*`；回退链生效。
- M1：与 Host 方案相比，infer P50/P95 降低；无稳定性退化。
- M2：动态形状/批量可用；长稳测试通过；基准报告完成。
