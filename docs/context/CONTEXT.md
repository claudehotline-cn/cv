# CONTEXT（In‑Process Triton + MinIO + 控制/前端一体化）

## 背景与范围
- 核心：`video-analyzer` 以内嵌（In‑Process）方式集成 Triton（libtritonserver），模型仓库迁移到 MinIO（S3 兼容）。
- 控制与前端：统一通过 Controlplane HTTP 暴露最小集（Schema/发布/仓库/观测），`web-front` 提供发布、配置、观测 UI。
- 主要目录：
  - VA 源码：`video-analyzer/src/analyzer/triton_inproc_*.cpp|.hpp`
  - CP 服务：`controlplane/src/server/*.cpp`、CLI：`controlplane/src/cli/*.cpp`
  - 前端：`web-front/`（Vue3 + Vite + Element Plus）
  - 文档与脚本：`docs/examples/*`、`tools/*`

## In‑Process Triton 修复与增强
1) 编译与崩溃修复
- 移除废弃的 `TRITONSERVER_InferenceRequestSetBatchSize`；批次由输入形状推断（支持 assume_no_batch 去前导 1 维）。
- 使用三参释放回调 `TRITONSERVER_InferenceRequestSetReleaseCallback`，异步入队后不再手动 Delete，避免双重释放。
- 生命周期修复：会话持有 `shared_ptr<TritonInprocServerHost>`，避免每帧析构导致 30s 等待日志。

2) ServerOptions 系统化（Host）
- 支持：`backend_dir`、Pinned/CUDA 内存池（设备粒度）、`backend-config` 注入（等价 `--backend-config=backend:key=value`）。
- 读取相关环境变量（如 `TRITON_BACKEND_DIR`、`TRITON_PINNED_MEM_MB`、`TRITON_CUDA_MEM_POOL_BYTES`、`TRITON_BACKEND_CONFIGS`）。

3) I/O 与 Warmup（Session）
- 输入支持 GPU 直通；输出分配器实现 size‑class 显存池（`next_pow2` 上取整复用），CPU 回退保留。
- 懒加载 Warmup：首帧按 `warmup_runs`（auto/-1=1 次）执行预热，避免冷启动抖动。

## MinIO（S3）仓库接入
- 端点与变量：兼容 AWS/S3 多前缀，推荐内嵌端点 URL：`s3://http://minio:9000/cv-models/models`；容器内健康检查与 AK/SK 签名验证通过。
- VA 配置字段：`triton_repo`、`triton_model(_version)`、`S3_*`/`AWS_*` 环境变量。
- Host 封装：In‑Process 提供 `loadModel/unloadModel/pollRepository` 包装，CP 映射 HTTP 路由。

## Controlplane：HTTP 最小集与可观测
- 配置 Schema：GET `/api/ui/schema/engine`（字段：provider/device/warmup/triton_* 等）。
- 发布/切换：
  - POST `/api/control/set_engine` → AnalyzerControl.SetEngine。
  - POST `/api/repo/load|/unload|/poll` → RepoLoad/RepoUnload/RepoPoll。
  - POST `/api/control/release` → Triton：SetEngine(triton_model/version)+HotSwap("__triton__")；非 Triton：HotSwap(model_uri)。
- 可观测：
  - GET `/api/_metrics/summary`（请求总数、后端错误、SSE 连接、缓存命中/未命中）。
  - GET `/metrics`（Prometheus 文本）。
  - GET `/api/va/runtime`（provider/gpu_active/io_binding/device_binding）。

## 前端（web-front）对接
- M1：接入 Runtime/Summary（顶栏 5s 刷新）；Dashboard 请求总数接入。
- M2：EngineForm（Schema→表单）与 Settings 保存（优先 `/api/control/set_engine`）。
- M3：Release 页面（Triton/非 Triton 路径）与统一发布端点 `/api/control/release`。
- M4：Models 页面仓库 Load/Unload/Poll 按钮。
- Dev 代理：Vite proxy 将 `/api`、`/metrics` 指向 CP（18080）。

## Ensemble 示例与取舍
- 单步封装：`ens_det_trt`/`ens_det_onnx`（仅转发到子模型）。
- 全链路示例：`ens_det_*_full`（Python Backend 前处理/后处理：`preproc_letterbox`、`yolo_nms`；演示用途，CPU 实现）。
- Overlay 不建议纳入 Ensemble（渲染/推流在 VA，更高效）；生产推荐将 NMS 融合至 TRT 插件（EfficientNMS）。

## 调优与验收
- 压测工具：`tools/triton/perf_analyze.sh`（封装 perf_analyzer），`tools/triton/suggest_dynamic_batch.py`（从 CSV 生成 `preferred_batch_size`）。
- 风险脚本：`tools/release/va_fallback.sh`（降级至 CUDA），`tools/release/va_restore_triton.sh`（恢复 Triton 并 HotSwap）。
- 验收：`tools/validate/e2e_smoke.sh`；`docs/examples/acceptance_checklist.md`。

## 现状与下一步
- In‑Process 稳定（生命周期/释放/显存池/预热）；MinIO 仓库打通；控制/前端发布链路闭环；可观测接口到位。
- 建议：
  - 生产启用 MinIO TLS 与凭据管理；
  - 优化 EngineForm 字段分组与提示；
  - 扩展 model_analyzer 自动搜索；
  - 将 NMS 融入主干引擎或 C++ Backend（GPU）。
